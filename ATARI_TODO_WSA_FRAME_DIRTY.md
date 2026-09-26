# WSA-frame dirty precision (pending investigation)

## Symptom / measurement
Hatari CPU profiling (`atari-st-planar-present`, branch `atari-st-c2p-pairlut`
present-mode intro run, `hatari --profile` via `profile save`, 8021247 Hz
clock, whole intro playback) shows `_c2p1x1_4_st` alone at **48.1% of all
accounted cycles** (771.7M of 1603.4M cycles, 88.0M instructions), with WSA
decode (`Format80_Decode` + `Format40_Decode*`) another ~15% on top of that.
It is by a wide margin the single largest cost in the intro, and present
mode (see `ATARI_SCREEN0_PLANARIZATION.md`) has already eliminated the
double-conversion and masked-edge overhead around it -- what is left is
overwhelmingly the unavoidable-looking cost of the c2p pass itself.

Comparison run against `atari-st-c2p-pairlut-blitter` at the identical clock
showed that branch spends **22% more** cycles/instructions inside
`_c2p1x1_4_st` (940.6M cycles / 107.4M instructions) than present mode does,
confirming the Blitter-accelerated chunky *copy* does nothing to reduce c2p
*conversion* cost -- the two are orthogonal, and present mode currently wins
on this axis. This note is about narrowing the conversion work itself,
which would benefit either design.

## Hypothesis (not yet measured)
Every intro WSA frame is presented as a single rectangle covering the whole
picture area (`GameLoop_PlayAnimation()`, `posX = 8, posY = 24`, up to
`304 x 143`, later widened to 16px groups by
`Video_Atari_PresentChunky()`). Format40/Format80 delta decoding is
run-length based -- most frames change only a fraction of the picture's
pixels (a character's mouth, a rocket's exhaust, a flag), yet the present
hook converts the *entire* picture rectangle to planar every single frame,
because `Video_Atari_PresentChunky()` has no visibility into which bytes
Format40/80 decoding actually touched -- it only knows the caller's nominal
rectangle.

If most frames only touch a modest fraction of the picture, converting the
whole rectangle every time is the dominant source of waste, and could
plausibly account for a large share of that 48% figure.

## Possible approaches (unexplored)
1. **Row/column dirty tracking inside the WSA decoder.** Format40/80 decode
   already walks the delta stream and knows exactly which destination bytes
   it wrote. Recording a per-16px-column-per-row bitmap (or even just a
   tight bounding box) during decode, and handing that to
   `Video_Atari_PresentChunky()` instead of the whole picture rectangle,
   would let present mode convert only what changed -- exactly the same
   idea as `g_dirty_blocks[]`, but computed from the delta stream instead
   of from `GFX_Screen_SetDirty()`'s caller-supplied box.
2. **Measure first.** Before building anything, instrument
   `Format40_Decode`/`Format80_Decode` (or add a one-off host/Hatari trace)
   to record actual touched-byte counts per frame across the intro, and
   compare against the picture area (304 x 143 = 43472px) to see how much
   headroom this really offers. If most frames touch >70-80% of the
   picture anyway (plausible for full-screen fades/dissolves, less so for
   character animation), the payoff may not justify the complexity.
3. Any such change is orthogonal to (and layers on top of) present mode --
   it narrows the rectangle present mode is handed, it does not change the
   present-mode mechanism itself.

## Status
Not investigated further. Recorded as a candidate for after phase 3
(viewport/`SCREEN_1` direct planar presentation, see
`ATARI_SCREEN0_PLANARIZATION.md` migration phases) lands, since phase 3
affects normal gameplay (continuous) rather than the intro (one-shot), and
is the higher-priority remaining item.
