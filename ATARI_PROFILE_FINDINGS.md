# Atari ST/STE — Real Hatari Profiler Findings

## Synchronous cursor comparison (2026-09-30)

Inputs: `opendune_prehwmouse.txt` (before) and `opendune_hwmouse.txt`
(after), similar late-scenario-1 gameplay while harvesters return and the
mission concludes. Both identify Hatari 2.3.1 / WinUAE and **16,042,494
cycles/second**: these are approximately 16 MHz captures, not stock 8 MHz ST
measurements. The mouse remains CPU-rendered; "hwmouse" is the capture name,
not an actual hardware sprite.

Use the dependency-free reader in `tools/hatari_profile_compare.py`:

```sh
python3 tools/hatari_profile_compare.py opendune_prehwmouse.txt opendune_hwmouse.txt
python3 tools/hatari_profile_compare.py opendune_prehwmouse.txt opendune_hwmouse.txt \
    --match 'Mouse|Cursor|Planar|Present|c2p|Video_Tick|GUI_DrawSprite' --top 35 \
    --json comparison.json
python3 -m unittest discover -s tools -p 'test_hatari_profile_compare.py'
```

It accepts Windows CRLF, ignores the incorrect embedded `Field regexp`,
folds local assembly labels into their parent functions, and separately
attributes ROM/cartridge instructions. GST symbols are truncated and can
collide; duplicate names are aggregated, with entry addresses retained in
JSON. `gst2ascii -a -b -d -l -o bin/opendune.tos` extracts the executable's
text-relative symbols, but that executable must match the captured build.
Do not apply the current binary's addresses to both profiles.

### Overall throughput

| Metric | Before | After |
|---|---:|---:|
| Profiled CPU cycles | 767,305,724 | 776,600,560 |
| CPU-equivalent seconds | 47.830 | 48.409 |
| TOS 200 Hz clock estimate | 47.830 s | 48.410 s |
| Executions of Video_Tick entry instruction | 987 | 857 |
| Video_Tick entry executions/second | 20.64 | 17.70 |
| GameLoop_Unit entry executions | 977 | 822 |
| Game-loop entry executions/second | 20.43 | 16.98 |
| Assembly c2p 16-pixel groups | 173,205 | 186,200 |
| Assembly-converted pixels | 2,771,280 | 2,979,200 |
| Assembly cycles/16-pixel group, including setup | 643.77 | 643.11 |

Video callback throughput is **14.2% lower**, and game-loop throughput
**16.9% lower** in the after capture. These are callback/loop rates, not
measured distinct displayed frames or proof of an identical-workload
regression. The new capture converts 7.5% more assembly pixels and executes
more tile draws (4,208 versus 3,941 entry executions). Immediate transparent
presentation also has substantially different activity. Total cycles alone
do not measure speed: the after capture is about 1.2% longer.

### Mouse work versus common writer overhead

The `_Mouse_EventHandler` call records show inclusive costs of
1,862,312 cycles for 19 calls before versus 36,752 for 10 calls after:
about **98,016 versus 3,675 cycles/event**. The movement-to-`GUI_Mouse_Show`
edge similarly drops from approximately 100,636 to 2,336 cycles/call.
These are different mouse-interaction samples, and actual planar cursor
reconciliation still runs separately in `CursorSync`.

The old profile executes `CursorPrepare` 33 times and `CursorBuild` 18
times; neither fallback routine appears as executed in the new capture.
`CursorSync` costs 615,052 exclusive cycles (0.079% of the new capture).
`PlanarFinishRun`, including the initial overlap tests and its own work,
costs 553,396 exclusive cycles (0.071%). The post-c2p overlap hook is
therefore not the large cost here.

The common masked/transparent writer path is much more significant:

| Exclusive function cost | After cycles | After share |
|---|---:|---:|
| Video_Atari_PlanarMergeGroup | 21,803,760 | 2.808% |
| Video_Atari_CursorWriteGroup | 16,814,148 | 2.165% |
| Combined, without double-counting | 38,617,908 | 4.973% |

Both entry instructions execute 25,270 times; the call table records
25,264 subroutine entries into `CursorWriteGroup`, with exception returns
accounting for the difference. Only **15** group operations reach the
mouse-overlap path (`0x70400` in MergeGroup, `0x6f1f2` in CursorWriteGroup).
Thus **99.94%** of these operations do not overlap the drawn mouse.
Placement processing is also bypassed: the placement count test at
`0x70424` skips directly to the ordinary merge in this capture.

The checks occur twice: `PlanarMergeGroup` obtains cursor-free background,
then `CursorWriteGroup` checks the same geometry again before storing.
Approximately 87% of the recorded MergeGroup subroutine calls (22,014
out of 25,259) come from immediate transparent presentation. This is
mostly common writer overhead, not actual mouse motion or overlapping
battlefield blits. However, the full 4.973% is **not** pure incremental
overhead: these routines also perform ordinary masked merging/storing
that previously lived inline in presentation functions.

Sprite rendering was split, not eliminated: compare old `GUI_DrawSprite`
against new `GUI_DrawSprite` **plus** `GUI_DrawSpriteInternal`. Their
exclusive totals are 158,691,312 versus 150,082,720 cycles; per entry,
approximately 9,596 versus 9,417 cycles. A comparison of the wrapper alone
would falsely suggest an enormous speedup.

### Interpretation / next optimization

The correctness improvement comes with measurable common-writer cost.
The first candidate is a cursor/placement-free masked/transparent path
selected once per rectangle/run, retaining the current clean-background
merge for overlapping writes. Passing/reusing destination pointers and
avoiding repeated per-group overlap checks are also candidates. Preserve
the synchronous backup invariant; do not restore the old delayed erase.

This capture cannot assign the entire 14-17% throughput difference to
the cursor change. A matched replay with identical mouse input and render
work is needed for a causal speed measurement. The profiles nevertheless
identify a concrete hotspot worth optimizing. Periodic dirty-sweep Warning
reports are not visible in these captures; Warning has only one entry in
each.

### Source stride and invocation size

Source stride is the byte distance between source scanlines, **not the
rectangle width**. A 32x16 rectangle in SCREEN_1 has stride 320 and can
use one multi-row assembly call. A tightly packed 32x16 private buffer has
stride 32 and needs separate assembly calls per row if presented opaquely.
Transparent presentation uses scalar conversion/merging instead.

The captured stride branches show:

| Recorded assembly c2p calls | Before | After |
|---|---:|---:|
| Sweep | 874 | 891 |
| Direct presentation, stride 320 | 249 | 259 |
| Direct presentation, other stride | 0 | 0 |

Before, the stride comparisons at `0x72494` and `0x7268c` lead directly
to the 320-stride calls at `0x7259e` and `0x727dc`; the intervening
per-scanline branches have no executed instructions. After, comparison
`0x71332` branches to the 320-stride call at `0x71666` for all 259 calls.
The `(T)/(F)` annotations in disassembly describe the debugger's current
condition state, not historical taken/not-taken totals.

Cursor preparation does not call `_c2p1x1_4_st`. It uses CursorBuild or
CursorBuildPhase with an explicit stride, and normal movement uses
pre-shifted cached bitplanes. Padding its private chunky buffer to a
32-byte row would not eliminate any general c2p calls in these captures.

### Overlay-free fast-path capture: `opendune_hwmouse2.txt`

The new capture spans 50.025 seconds by the TOS clock (802,562,040 CPU
cycles, 50.027 CPU-equivalent seconds), still at 16,042,494 cycles/second.
Warning has only one entry and no periodic sweep logging is visible.

| Metric | Pre-synchronous cursor | Synchronous cursor | Overlay-free fast path |
|---|---:|---:|---:|
| TOS-clock seconds | 47.830 | 48.410 | 50.025 |
| Video_Tick entry executions | 987 | 857 | 1,022 |
| Video_Tick entries/second | 20.64 | 17.70 | 20.43 |
| GameLoop_Unit entry executions | 977 | 822 | 946 |
| Game-loop entries/second | 20.43 | 16.98 | 18.91 |
| Assembly-converted pixels | 2,771,280 | 2,979,200 | 2,805,376 |
| Assembly pixels/Video_Tick entry | 2,808 | 3,476 | 2,745 |
| Assembly cycles/16-pixel group | 643.77 | 643.11 | 643.54 |

Relative to `hwmouse`, callback throughput improves **15.4%** and
game-loop throughput **11.4%**. The callback rate is within **1.0%** of
the pre-synchronous-cursor capture; game-loop throughput remains 7.4%
below that older capture. As before, these are callback/loop rates,
not distinct displayed-frame counts or identical-replay timing.

The target hotspot is removed from almost all writes:

| Exclusive cost | hwmouse | hwmouse2 |
|---|---:|---:|
| PlanarMergeGroup | 21,803,760 cycles | 127,104 cycles |
| CursorWriteGroup | 16,814,148 cycles | 105,328 cycles |
| Both helpers' entry executions | 25,270 each | 152 each |
| New rectangle-level overlap test | — | 773,336 cycles |
| Helpers plus rectangle test, capture share | 4.973% | 0.125% |

The two group helpers' exclusive cost drops **99.4%**. Including the new
rectangle-level selection, their combined cost is approximately 1.01
million cycles, versus 38.62 million before. Ordinary merging now lives
inline in the fast path, so the increased PresentChunky symbol total is
not by itself a regression. Summing PresentChunky, PresentGroupMasked,
PlanarFill, PlanarMergeGroup, CursorWriteGroup and PlanarOverlaysOverlap
accounts for that movement: 132,147,884 versus 109,817,424 exclusive
cycles, or **17.02% versus 13.68%** of each capture. This aggregate's
cycles/second fall about 19.6%, despite more immediate-presentation entries.
Workloads are still not identical.

Mouse_EventHandler remains cheap: 86,884 inclusive cycles for 22 calls,
approximately 3,949 cycles/event. c2p batching remains intact: 876 sweep
calls and 255 direct calls use the same multi-row paths; no non-320-stride
assembly call path is recorded.

#### Additional difference: decoded-tile alignment fallback

The new capture has 32,119 `_memmove` entry executions and 14,826,584
exclusive cycles (1.847% of total), compared with 104 entries and 86,780
cycles in `hwmouse`. Almost all are cached-tile row copies: the call table
records 16,003 calls at each of two unrolled call sites in GFX_DrawTile.

This is **a different runtime branch, not new cursor code**. At the
four-byte-alignment check (`0x1e118`), all 2,179 eligible opaque cached-tile
draws in `hwmouse` enter the inline-copy path. All 2,001 corresponding
draws in `hwmouse2` instead enter the library-copy fallback. The condition
is `((wptr | dr | rowBytes) & 3) == 0` in `src/gfx.c`. The captures do not
establish which pointer fails the alignment check or why its alignment
differs. This separate hotspot is worth investigating before attributing
the remaining difference from the oldest capture to cursor handling.

**Stationary follow-up:** the pair below does not reproduce the fallback
in either build. The alignment issue remains deferred until it can be
reproduced and the decoded-tile source/screen destination addresses checked.
Do not assume the cursor caused it. No tile-copy changes have been made
for this finding.

**Proposed isolation (not implemented):** add a compile-time-gated diagnostic
at the exact opaque decoded-tile alignment branch in `GFX_DrawTile`.
On the first fallback, or first new failure signature, record the active
screen ID, tile ID, x/y, rowBytes/height, decoded-cache base, screen-buffer
base, `dr`, `wptr`, and each relevant value modulo four. Classify the
failure as source alignment, destination alignment, row width, or a
combination. Log screen/cache allocation addresses once at initialization
or cache rebuild as well. This separates a persistently misaligned base
from an odd widget x offset, a different destination screen, or a cache
reallocation.

Count fast/fallback tiles and estimated row-copy calls by screen and failure
reason; emit at most one aggregate per interval, not one line per row.
Include a timestamp so the first fallback can be related to mouse movement,
edge scrolling or GUI transitions. Compile the diagnostic completely out
for timing comparisons. A Hatari breakpoint at the fallback entry can also
inspect actual pointers on one stopped occurrence without a logging patch.
The existing profile disassembly annotations show debugger-time state,
not the historical arguments of every call, so they cannot identify the
failing pointer retrospectively.

The condition itself has no mouse-coordinate dependency. Once a decoded
cache and destination screen allocation are fixed, cursor movement alone
does not change their base alignment. Mouse-induced scrolling, different
widget/screen routing or allocation history remain hypotheses to check,
not established causes. The diagnostic is small and should identify the
immediate cause quickly when the fallback is reproduced.

### Stationary pair isolating the uncommitted work

Inputs: `opendune_prevhwmouse_still.txt` versus
`opendune_hwmouse_still.txt`. The user identifies this pair as covering only
the current uncommitted-work difference, with no mouse movement or player
input. Both already contain the committed synchronous cursor implementation;
this is not a comparison against the old cursor design.

| Metric | Before uncommitted changes | After |
|---|---:|---:|
| CPU cycles | 782,049,224 | 746,472,434 |
| TOS-clock duration | 48.750 s | 46.530 s |
| Video_Tick entry executions | 848 | 858 |
| Video callbacks/second | 17.39 | 18.44 |
| GameLoop_Unit entry executions | 866 | 900 |
| Game-loop iterations/second | 17.76 | 19.34 |
| Assembly-converted pixels | 2,827,264 | 2,870,336 |
| Assembly pixels/Video_Tick entry | 3,334 | 3,345 |
| Assembly cycles/16-pixel group | 643.60 | 643.42 |
| GFX_DrawTile entry executions | 3,982 | 3,983 |

Video callback throughput improves **6.0%**, game-loop throughput **8.9%**.
The after capture converts **1.5% more assembly pixels in 4.6% less
captured time**, approximately **6.4% more pixels/second**. Converted area
per callback is essentially unchanged (+0.34%). This supports a real
throughput improvement without mouse movement, not merely less conversion.
These remain callback/loop rates rather than unique displayed-frame counts,
and the GUI-presentation mix still differs; the pair is not a deterministic
frame-for-frame replay.

#### Fast-path cost and genuine stationary overlaps

| Exclusive cost | Before | After |
|---|---:|---:|
| PlanarMergeGroup | 23,460,288 cycles | 2,990,744 cycles |
| CursorWriteGroup | 18,949,280 cycles | 4,158,760 cycles |
| Both helpers' entry executions | 31,294 each | 3,245 each |
| Rectangle-level overlap selection | — | 378,276 cycles |
| Group helpers plus selection, capture share | 5.423% | 1.008% |

Group-helper entries fall **89.6%**, and their exclusive cycles **83.1%**.
Accounting for ordinary merge work moving into parent functions, the same
common-writer aggregate used above drops from **146,453,672 to 107,482,600
cycles**: **18.73% to 14.40%** of total cycles, or **23.1% fewer writer
cycles/second**.

No Mouse_EventHandler execution appears in either capture. The remaining
after-profile MergeGroup calls are recorded from PlanarFinishRun (2,480)
and PlanarFill (765), not the ordinary transparent-presentation path.
A stationary pointer still needs maintained backups when underlying pixels
are written, even if their final values are unchanged; a rectangle classified
as overlapping also conservatively keeps the backup-aware path for its groups.
The remaining calls should not
be described as mouse-movement cost.

CursorSync and its memcmp work remain similar in both captures:
approximately 6.54 versus 6.58 million exclusive cycles combined, around
0.84% versus 0.88% of total CPU cycles. Neither profile contains periodic
sweep logging: Warning has one entry in each.

#### Deferred tile-copy hotspot is absent here

The cached-tile alignment tests execute 1,986 versus 2,035 times and use
the inline-copy path in both captures. There are **no GFX_DrawTile-to-memmove
call records**. Total memmove entry executions are 104 versus 101, costing
86,724 versus 83,708 cycles (about 0.011% of each capture).

Thus the roughly 32,000 tile-row-copy calls / 1.85% CPU cost from
`hwmouse2` are not a consistent consequence of the uncommitted fast path.
They are conditional on a runtime alignment difference that these
stationary captures do not reproduce. Leave that investigation separate.

### Sparse viewport rows: `opendune_viewport_dirty_gaps.txt`

Compared against `opendune_hwmouse_still.txt`, the previous overlay-free
cursor build. Both captures use 16,042,494 cycles/second, have no recorded
Mouse_EventHandler execution, and contain only one Warning entry (no
periodic sweep logging). The new viewport disassembly includes the added
column-mask initialization and cached CursorDirect test, confirming the
capture contains the sparse-row implementation.

| Metric | Previous still | Dirty gaps | Change |
|---|---:|---:|---:|
| TOS-clock duration | 46.530 s | 47.810 s | +2.75% |
| Video_Tick entry executions | 858 | 891 | +3.85% |
| Video callbacks/second | 18.44 | 18.64 | +1.07% |
| GameLoop_Unit entry executions | 900 | 922 | +2.44% |
| Game-loop iterations/second | 19.34 | 19.28 | -0.30% |
| Assembly-converted pixels | 2,870,336 | 2,758,016 | -3.91% |
| Assembly pixels/video callback | 3,345 | 3,095 | -7.47% |
| Assembly pixels/second | 61,688 | 57,687 | -6.49% |
| Assembly cycles/16-pixel group | 643.42 | 644.97 | +0.24% |
| Assembly c2p calls | 1,123 | 1,223 | +8.90% |
| Assembly c2p calls/video callback | 1.309 | 1.373 | +4.87% |
| Average pixels/assembly call | 2,556 | 2,255 | -11.77% |

Overall throughput is essentially unchanged in this capture, consistent
with the user's expectation that this scene has limited gap-removal
opportunity. Nevertheless, assembly conversion coverage is lower despite
the longer capture. Its exclusive cycles/second fall **6.26%**, from
2.481 million to 2.325 million. The pixel figures exclude scalar
masked/transparent conversion and measure workload, not unique pixels.

Sweep calls increase from 867 to 963; direct multi-row calls remain
approximately unchanged (256 versus 260 recorded calls, including possible
exception re-entry). Splitting real horizontal gaps naturally produces
more, smaller rectangles. Average assembly calls still cover thousands of
pixels, not individual 16-pixel stripes. Equal-mask vertical banding and
contiguous horizontal runs are retained.

Isolating GUI_Widget_Viewport_Draw from DrawTile (both truncate to the same
GST name), its exclusive cost is 31,264,148 versus 32,271,036 cycles:
34,738 versus 35,001 cycles/entry, a **0.76%** increase. This includes
composition and marking, not child functions. Dirty-viewport marker entries
increase from 1,870 to 1,977, with exclusive cost 2,479,240 versus 2,619,288
cycles. Normalized marker cost rises about 2.82%; the added marking work
is small relative to the observed c2p reduction.

**Important workload difference:** the new capture also contains 1,791
extra GFX_Screen_Copy calls from the inner loop of GUI_Screen_FadeIn:
8x2-pixel pieces, absent from the previous still capture. The fade's entry
is not recorded, so this is a captured tail of a fade already in progress.
Its loop-to-copy call edge accounts for **17,727,484 inclusive cycles**
(2.31% of the new capture), including descendant writer work; do not add
that inclusive total to descendant function totals.

These copies explain the large extra masked-writer activity:
PresentGroupMasked entries rise from 1,204 to 4,816 and its exclusive cost
from 3.05 million to 12.20 million cycles. This is not the sparse viewport
falling back to per-tile immediate presentation. The new c2p sweep still
reads the independently marked SCREEN_1 viewport.

The profile omits the unexecuted GUI_Screen_FadeIn entry label, so the
standalone reader attributes that unlabelled loop to the preceding
GUI_Mouse_Hide_InRegion symbol. Resolved against the matching current
binary's gst2ascii symbols: load base 0x10be0, fade range
0x2730e..0x275ec, copy call at 0x274b8. The loop contributes 798,324
exclusive cycles; it must not be mistaken for a new mouse-hide hotspot.
The six-function common-writer aggregate rises from 14.40% to 15.86%,
but the extra fade work prevents interpreting that as a viewport regression.

No cached-tile-to-memmove fallback appears in either capture. Cursor group
helper calls do not fall materially (3,245 versus 3,438; approximately
2% more per video callback), so this scene does not demonstrate a reduction
in stationary-cursor background maintenance.

Conclusion: modest conversion-area savings, retained batching and nearly
flat observed throughput. The captures contain different GUI phases and
are not a clean gameplay-only replay; the 7.47% per-callback reduction is
an observed workload difference, not an isolated exact gap-removal speedup.

## Earlier palette/c2p investigation

Source: user-captured Hatari CPU profile (`opendune_profile.txt`, WinUAE core,
16,042,494 cycles/sec, ~65.25s of gameplay captured), post-processed with
`hatari_profile` (bundled `tools/debugger/hatari_profile.py`).

Two mechanical fixes were needed before the tool would parse the file:
1. File had CRLF line endings — stripped with `sed -i 's/\r$//'`.
2. The embedded `Field regexp:` line (`^\$([0-9a-f]+) :.*% \((.*)\)$`) didn't
   match this Hatari version's actual disassembly line format (no leading
   `$`, space before the percentage rather than ` :`). Fixed to:
   `^([0-9a-fA-F]+) .*% \((.*)\)$`.

Command used: `hatari_profile -st -f 25 opendune_profile.txt`

## Top "Used cycles" consumers (whole 65s capture)

| % of cycles | Function              |
|------------:|------------------------|
| 23.68%      | `_Video_SetPalette`   |
| 17.29%      | `_c2p1x1_4_st`        |
| 5.16%       | ROM_TOS               |
| 4.62%       | `_GFX_DrawTile`       |
| 4.13%       | `_GUI_DrawSprite`     |
| 3.43%       | `_GUI_Widget_HandleEven` |
| ...         | (toupper/strcasecmp/timer/etc — mostly TOS/libc overhead) |
| 1.13%       | `_GFX_Screen_Copy`    |
| 0.87%       | `_Video_Tick`         |

**Headline surprise: `Video_SetPalette` (palette → pair-LUT rebuild) costs
*more* total cycles than the c2p routine itself**, despite the partial-rebuild
optimization already in place (commit `d7bb6647`, this branch).

## Root cause, located in the profile

Inside `_Video_SetPalette`, address `0x6EFE8`-`0x6EFF2` is executed
**1,935,360 times** — the single hottest instruction cluster in the *entire*
captured session (higher execution count than anything in the game loop,
c2p, tile drawing, or sprite drawing):

```asm
CLR.W    D0
MOVE.B   (A0)+,D0
OR.W     D1,D0
MOVE.W   D0,(A1)+
CMPA.L   D2,A0
BNE.B    ...
```

This is the inner loop of `Rebuild_Palette4BitPairMap()`
(`src/video/video_atari.c:89`) that patches `s_palette4BitPairMap[65536]`.

## Why the "partial rebuild" optimization doesn't help as much as hoped

`Rebuild_Palette4BitPairMap(from, length)` has two paths:
- `length >= 64`: full rebuild, 65536 entries touched (256×256).
- `length < 64` (typical case — animating 1 color): patches
  - the `length` full rows for changed `hi` indices (256 words each), **and**
  - the `length` columns in *every other row* (i.e. all ~256 `hi` values,
    each touched once per changed `lo`).

  **Even a single-color change (`length == 1`) therefore still touches all
  256 rows** (one row fully rewritten as the "hi" case, or one word in each
  of the other 255 rows as the "lo" case) — i.e. the minimum cost of *any*
  palette change, no matter how small, is O(256) word-writes, not O(1).

This matters because `GUI_PaletteAnimate()` (`src/gui/gui.c:643`) drives
several *single-color* animations continuously during normal play:
- repair-button flash (color 239) — every 60 ticks
- selection-color cycling (color 255) — every **3 ticks**
- windtrap glow (color 223) — every 5 ticks

Each of these calls `GFX_SetPalette(g_palette1)` →
`Video_SetPalette(..., from, length)` with `length` typically 1 (or a small
range if multiple animated colors changed the same frame), which still costs
~512 word-writes (256 row-patch + 255 column-patch entries) per call. With
selection-color cycling alone firing every 3 ticks (~20×/sec at 60Hz), plus
the other two animators, this adds up to the dominant cost seen in the
profile — **the pair-LUT scheme trades a large one-time win (for tile/sprite
draw, avoiding a runtime remap) for a per-animation-tick cost that's more
expensive than expected for the extremely common "1 color changed" case.**

## Candidate directions (not yet designed/implemented)

1. **Cap the per-frame palette LUT patch cost** by deferring/coalescing
   multiple small `Video_SetPalette` calls within the same tick into one
   patch pass (if `GUI_PaletteAnimate` can change 3 unrelated colors in one
   frame, currently each triggers its own full `GFX_SetPalette` → separate
   `Rebuild_Palette4BitPairMap` call already covers `[min,max]` of *that one*
   `GFX_SetPalette` call — but the 3 animators in `GUI_PaletteAnimate` call
   `GFX_SetPalette` only if `shouldSetPalette`, and it's called once at the
   end for all three combined, so this may already be partially coalesced —
   needs verification of actual `from`/`length` values seen in practice).
2. **Rethink the pair-LUT data structure** so a single changed color doesn't
   require an O(256) patch. E.g.:
   - Keep the 65536-entry pair table only for *static* (rarely-changing)
     palette contents, and handle the 2-3 known "always animating" indices
     (239, 255, 223) via a cheaper mechanism (e.g. a small per-pixel remap
     applied at c2p time only for pixels matching those specific chunky
     values, or restrict animation to colors known not to appear in
     high-frequency redraw paths).
   - Or drop the pair-LUT and go back to a plain 256-entry single-pixel
     remap table, doing the pairing arithmetic (`hi<<8 | lo`) at c2p time
     instead of via a precomputed 64K table — trades some c2p-side cycles
     for O(1) (not O(256)) palette-change cost. Would need re-measuring
     actual c2p cost delta given real profile data now available.
3. Instrument/log actual `from`/`length` values passed into
   `Rebuild_Palette4BitPairMap` during a play session (or re-derive from
   the profile's caller info) to confirm how often length is 1 vs larger,
   before picking a fix — avoid guessing.

## Master-branch baseline comparison

A second profile was captured on `master` (pre-pairlut, plain per-pixel
remap in `c2p1x1_4_st`, no `s_palette4BitPairMap`) for comparison:
`opendune_master.txt`, same tooling/fixes applied.

Captures are different play sessions of different lengths (master capture:
38.56s; pairlut-branch capture: 65.25s), so raw totals aren't directly
comparable — normalized to **cycles/second of captured session**:

| Function            | master (cycles/s) | pairlut branch (cycles/s) |
|----------------------|-------------------:|---------------------------:|
| `_c2p1x1_4_st`       | 8,858,963          | 2,774,087                  |
| `_Video_SetPalette`  | 965,789            | 3,799,405                  |
| **combined**         | **9,824,752**       | **6,573,491**              |

Takeaways:
- The pair-LUT c2p optimization delivers a **real, large win** on the c2p
  routine itself: ~3.2x fewer cycles/sec spent in `_c2p1x1_4_st`.
- But `_Video_SetPalette` cost **~3.9x increase** in cycles/sec, confirming
  the O(256)-per-change patch cost is a real regression introduced by the
  pair-LUT scheme (master's plain 256-entry remap has no equivalent
  per-change patch cost anywhere near this size).
- Net effect is still a win (combined ~33% fewer cycles/sec), but the
  palette-rebuild regression has eaten a large fraction of the c2p gain —
  more than expected going in. This strongly motivates fixing the
  `Rebuild_Palette4BitPairMap` cost (see candidate directions above) to
  capture more of the c2p optimization's full potential.
- Caveat: the two sessions may not have exercised identical gameplay content
  (different scenes/animation activity), so this is a directional signal,
  not an exact A/B measurement. A same-scenario re-capture (identical input
  script/replay on both branches) would give a cleaner comparison.

## Status

Diagnosed only from real profiler data — **no code changes made**. This
finding takes priority over further `c2p1x1_4_st` micro-optimization (MOVEP
etc., see prior discussion) since `Video_SetPalette`'s regression is
currently offsetting a large fraction of the c2p win.
