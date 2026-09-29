# TODO: finish turning the Atari cursor into a "hardware sprite"

## Current implementation: synchronous planar updates

Implemented for ST/STE and visually confirmed by the user. The older findings
and proposals below are retained as investigation history, not the current
cursor algorithm.

The invariant is now: `s_curSave` always holds the latest mouse-free image at
the actual drawn cursor position. If a placement outline is present, that
outline is part of the mouse's background. Placement backups hold the scene
without either overlay.

- Opaque c2p runs keep their existing assembly loop. After conversion, only
  intersecting mouse/placement groups are revisited: their clean backgrounds
  are updated and the overlays are composited synchronously.
- Partial edges, transparent sprites and planar fills share a word-level merge:
  read the clean background, apply the write mask, update the placement backup,
  composite placement, update the mouse backup, then composite the mouse.
  Transparent pixels never capture mouse pixels into the backup.
- Saved screen regions exclude both overlays. Restores refresh the backups
  and reapply the current overlays. Planar shifts validate their geometry,
  remove overlays before reading/moving screen memory, then rebuild them
  synchronously; this remains the explicitly allowed brief-removal exception.
- Both dirty-block sweeps and the full ST/STE repaint path finish their c2p
  runs through the same overlay update. Placement drawing/restoration is
  mouse-aware. The small ST FPS overlay also uses the shared merge.
- The former `s_curEraseHit`, `s_curNeedErase` and dirty-coverage-based deferred
  cursor erase are removed. `Video_Tick()` reconciles final requested position,
  visibility and appearance with the actually drawn state. An unchanged
  hide/show pair no longer causes an erase/redraw. Genuine moves/hides restore
  the continuously maintained backup.
- Actual on-screen cursor data/masks are snapshotted independently of requested
  caches (3840 bytes of additional static storage). This prevents a palette
  rebuild or an icon change from invalidating the currently drawn cursor before
  it moves. No extra chunky screen or maximum-sized stack scratch is introduced.

Cross-build validation targets the existing 68000 TOS configuration; c2p
assembly and TT/Falcon paths are unchanged. On 2026-09-30 the user reported
that all visual glitches and cursor garbage dragging disappeared together,
describing the improvement as tremendous. Performance has not been measured;
before/after profiling remains pending and no speedup is claimed.
Regression checks for future changes: opening/closing the construction-yard
hint, moving afterward, gameplay-to-Hall-of-Fame transitions, stationary
pointers under transparent sprites and partial-edge writes, viewport scrolling,
screen-edge clipping, and placement outlines under the pointer.

## Update: private cursor preparation

The first repair moves cursor preparation out of all game screen buffers.
`GUI_DrawSpriteToBuffer()` reuses the existing sprite decoder with an explicit
private destination, tightly packed row stride and buffer-local clipping.
It cannot take the direct-planar presentation path.

- Icon preloading renders into an exactly sized temporary heap buffer, crops
  the opaque bounds, then builds all 16 planar phases using the explicit
  source stride. It no longer clears, draws into or restores SCREEN_0.
- The uncached cursor fallback also uses a local, exactly sized heap allocation,
  released before returning. There is no fixed 96x64 scratch array on the stack.
  Those dimensions remain only the existing planar converter capacity limits.
  Allocation happens before `CursorPrepare()` updates its cache key, so a failed
  allocation cannot cause unbuilt data to be reused. Cached-icon movement does
  not allocate scratch memory.
- The direct-planar fallback no longer takes a chunky screen-background backup
  merely to prepare cursor pixels. Actual planar save/restore remains unchanged.

The old icon-preload call used `GUI_DrawSprite(SCREEN_0, ..., flags=0)`, which
could present its temporary sprite at the upper-left corner despite suppression
of dirty tracking. Private rendering removes that route to visible preparation.
The subsequent synchronous-writer implementation above was visually confirmed
by the user to eliminate cursor glitches and stale-background dragging.

## Corrections to the dirty-marking proposal below

The findings below identify redundant dirty-marking, but the suggested fix
is not sufficient on its own:

- `Video_Atari_CursorHide()` also sets `s_curDirty`. Skipping that assignment in
  Show/UseIcon cannot undo the earlier hide. Compare the final requested state
  against the last drawn state at presentation time, allowing temporary
  hide/show pairs to cancel while preserving genuine hides and screen overlaps.
- `CursorPrepare()`'s cache key describes converted sprite data, not absolute
  screen position. A vertical move or a move by 16 pixels can reuse the data
  while still requiring a screen redraw. Rebuild and redraw decisions must be
  separate.
- Multiple hide/show pairs can force a redundant redraw per video tick, not one
  redraw per pair. Explicit present/restore operations also have cursor-erasure
  paths outside the ordinary trailing tick erase/draw pair.
- `GUI_Mouse_*_Safe()` sleeps only while `g_mouseLock` is nonzero; an uncontended
  call does not sleep.

## Motivation

This port is very defensive about cursor visibility: nearly every widget
draw routine in `src/gui/gui.c` (71 call sites at time of writing) brackets
itself with `GUI_Mouse_Hide_Safe()`/`GUI_Mouse_Show_Safe()`, even when the
draw only touches an off-screen chunky buffer (`SCREEN_1`/`SCREEN_2`) that
is never directly presented. That convention dates from the original
cross-platform design, where the mouse cursor really was composited
straight into whatever buffer got drawn to and had to be physically
removed/restored around any write that might be under it.

On ST/STE (`Video_Atari_CursorDirect()` true), the cursor no longer works
that way at all: it lives purely in planar memory, composited on top of
the already-converted screen by `Video_Tick()`, fully decoupled from
`SCREEN_1`/`SCREEN_2` chunky content. The working hypothesis (raised while
discussing further optimization) was: make the planar cursor behave like a
real hardware sprite -- always "on" unless explicitly told otherwise, and
only pay any erase/composite cost when a blit actually overlaps its
current position. If most of that is already true, the remaining `Hide/Show`
noise sprinkled through widget code should be nearly free; if not, it is a
plausible source of both the visible flicker and constant CPU pressure
reported on busy battlefield frames (many structures animating
flags/radars/etc., each wrapped in its own Hide/Show pair).

## What is already implemented (more than expected)

Investigation of `src/video/video_atari.c` found the "hardware sprite"
design is already largely in place:

- `GUI_Mouse_Hide()`/`GUI_Mouse_Show()` on TOS, for the common icon-cursor
  case, do **not** touch planar memory synchronously at all. They only
  update state (`s_curVisible`, position, which icon's precomputed
  bitplane data to use) via `Video_Atari_CursorUseIcon()` /
  `Video_Atari_CursorPrepare()`.
- The actual planar erase (`Video_Atari_CursorErase()`) and recomposite
  (`Video_Atari_CursorDraw()`) only ever run from inside `Video_Tick()`
  (confirmed: `Video_Atari_CursorDraw()`'s only call site is
  `video_atari.c:3081`), i.e. **at most once per frame**, no matter how
  many Hide/Show pairs happened synchronously beforehand that tick.
- `Video_Tick()` already has real overlap-awareness:
  `Video_Atari_CursorOverlap()` checks whether this tick's c2p pass is
  going to reconvert the cursor's old rectangle anyway (in which case no
  manual erase is needed -- c2p already restored plain background there),
  is only going to partially cover it (manual erase still required, to
  avoid "biting a hole" in the cursor for a frame), or isn't going to
  touch it at all (screen not dirty near the cursor -> skip erase/redraw
  entirely). This logic already replaced an earlier, cruder
  "`GFX_Screen_IsDirty(SCREEN_0)` implies redraw" condition that a profile
  showed made the cursor system **44% more expensive per tick** than the
  chunky mouse-restore path it replaced -- see the large comment block
  around `video_atari.c:2600-2650`.
- Erase is deliberately deferred to immediately before the trailing
  redraw (not done eagerly when `Hide()` is called) specifically to keep
  the erase-to-redraw gap as small as possible on real hardware, since the
  screen is single-buffered and scanned asynchronously by the CRT with no
  vsync/double-buffer wait anywhere in this codebase -- any real elapsed
  time between erase and redraw is a visible one-frame "blink".
- `g_mouseHiddenDepth` already coalesces nested Hide/Show calls (only the
  outermost pair has any effect), so recursive widget nesting was not
  actually stacking redundant work.

None of this needed to be built from scratch -- it already reflects the
same "only pay when something actually overlaps" idea being proposed.

## The actual bug found: `s_curDirty` is forced true on *every* Show(), unconditionally

Despite all of the above, `Video_Tick()`'s decision of whether the cursor
was "touched" this tick is:

```c
bool touched = s_curDirty || s_screen_needrepaint || overlap != 0;
```

and `s_curDirty` turns out to be set `true` unconditionally by the code
paths `GUI_Mouse_Show()` actually takes, with **no comparison against the
previous frame's state**:

- `Video_Atari_CursorUseIcon()` (`video_atari.c:1498`, the fast path used
  whenever `g_mouseSpriteIconIndex != 0xffff` -- i.e. essentially always,
  for the standard pointer) sets `s_curDirty = true` on every single call,
  both on the normal path (`video_atari.c:1555`) and the "fully clipped
  off-screen" early-out (`video_atari.c:1542`). There is no check of
  whether `iconIndex`/`left`/`top`/palette generation actually differ from
  the last call.
- `Video_Atari_CursorPrepare()` (`video_atari.c:1219`, the fallback slow
  path) does have a dedup comparison (`sprite`/`w`/`h`/`shift`/`dx`/`dy`/
  palette generation, `video_atari.c:1245-1247`) that returns `false`
  ("cached form still applies, no need to rebuild bitplanes") when nothing
  changed -- **but `s_curDirty = true` is set unconditionally at
  `video_atari.c:1239`, before that comparison ever runs**, so even this
  path's own anti-duplicate logic cannot prevent the dirty flag from being
  forced.

Net effect: **every one of the 71 `GUI_Mouse_Show()`/`Show_Safe()` call
sites forces `touched = true` in `Video_Tick()` on whatever tick it runs,
regardless of whether the mouse moved, the icon changed, or the
underlying widget draw ever touched a visible buffer at all.** When the
screen isn't dirty near the cursor (`overlap == 0`), this still takes the
"must manually erase" branch (`s_curNeedErase = true`), because `touched`
being true only requires *one* of its three conditions, and `s_curDirty`
alone satisfies it. So a batch of animating structures each calling
`Hide_Safe()`/`Show_Safe()` around their own off-screen drawing, with the
mouse sitting perfectly still over blank ground the whole time, still
costs one full planar cursor erase+recomposite per tick -- the exact kind
of avoidable, per-tick, count-scales-with-widget-count cost the original
report suspected.

## Proposed fix (not yet implemented)

Purely inside `video_atari.c`, no changes needed to any of the 71 call
sites in `gui.c`:

1. Add a real equality check to `Video_Atari_CursorUseIcon()` (mirroring
   the pattern already used by `CursorPrepare()`'s slow path): remember
   the last `iconIndex`, `left`, `top`, and palette generation actually
   composited, and only set `s_curDirty = true` when at least one of them
   differs from this call's arguments.
2. Reorder `Video_Atari_CursorPrepare()` so `s_curDirty = true` is only
   set on the branch that actually returns `true` (real change requiring
   a rebuild), not unconditionally before the existing dedup check runs.
3. Re-verify the "fully clipped off-screen" early-out in `CursorUseIcon()`
   (`video_atari.c:1542`) still correctly marks dirty exactly once, on the
   transition into/out of "cursor is entirely off-screen" -- this is a
   real, if rare, visible-state change and must keep forcing a redraw when
   it actually happens (e.g. right at the moment the cursor first goes
   off-screen, so the old position gets erased).

This should eliminate the large majority of currently-redundant cursor
erase/recomposite work -- and, by extension, the associated flicker risk,
since fewer manual-erase branches means fewer erase-to-redraw gaps for a
CRT refresh to catch mid-way -- without touching widget code at all.

## Deferred / larger-scope idea (not started)

Separately, many of the 71 `Hide_Safe()`/`Show_Safe()` call sites bracket
draws that *only* ever touch `SCREEN_1`/`SCREEN_2` (never `SCREEN_0`)
between the pair -- for those, the calls are pure no-ops for TOS's planar
cursor (which cannot be visually affected by a buffer that is never
presented) and only cost the `g_mouseLock` spin/depth-counter overhead.
Trimming these would require an actual per-call-site audit (some
surrounding code sequences do eventually blit to `SCREEN_0` further down,
so the call is legitimate; some genuinely never do), and must preserve
current behaviour on non-TOS backends, where `SCREEN_0` *is* the live,
composited buffer and the existing Hide/Show calls are load-bearing. This
is real but strictly smaller-impact than the `s_curDirty` bug above (it
only saves cheap spin/branch overhead, not actual erase/recomposite work),
and riskier to get right across 71 sites. Recommendation: fix and profile
the `s_curDirty` bug first; only pursue this larger audit if profiling
still shows meaningful cursor-related cost afterward.

## Status

The historical dirty-marking-only proposal above was superseded by the
synchronous writer implementation described at the top. Visual improvement is
confirmed by the user; performance profiling on ST/STE remains pending.
