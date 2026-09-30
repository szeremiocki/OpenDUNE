# Banner text-scroll performance

## Current implementation

ST/STE now caches the existing two-line, 24-row banner composition in
3.75 KiB of word-aligned planar memory. Each animation tick blits its
14-row window at x=8..311, y=21..34. Full interior groups use row copies;
the partial horizontal edge groups use masked planar writes. Existing
cursor-aware helpers update clean backups and reapply the cursor.

The cache is converted once per slide, and rebuilt if the existing
g_textDisplayNeedsUpdate flag requests fresh text during a slide. Gameplay
palette/quantization are assumed static; there is no palette-generation
tracking. Message priority, queueing, timing and the 10-to-0 offset sequence
are unchanged. TT/Falcon and non-Atari rendering retain their original path.

Before this cache, current ST/STE GFX_Screen_Copy already bypassed the
SCREEN_0 chunky shadow and converted directly from SCREEN_1 on every tick.
It cleared the destination dirty blocks after presentation rather than
leaving a deferred Video_Tick sweep. The trace below describes the older
dirty-marking implementation, not the immediate pre-cache path.

## Symptom
Visible slowdown on Atari ST/STE when the one-line info banner (e.g. "Atreides
Trike") slides into the HUD, pushing the previous message down. Reported as
clearly noticeable, unlike normal gameplay (mouse-only) redraws.

## Original root cause
- Banner is widget index 7: `g_widgetProperties[7] = { xBase=1, yBase=21,
  width=38, height=14 }` (`src/gui/widget.c:41`). Width is in 8px units, so
  the widget is **304 x 14 pixels** on screen.
- `GUI_DisplayText()` (`src/gui/gui.c:242`, scroll block starting ~line 296)
  animates the slide by decrementing `textOffset` from 10 to 0, one tick at a
  time. Each tick calls:
  `GUI_Screen_Copy(g_curWidgetXBase, textOffset, g_curWidgetXBase,
  g_curWidgetYBase, g_curWidgetWidth, height, SCREEN_1, SCREEN_0)`
  (`src/gui/gui.c:327`) with `width = 38` (304px) and `height` up to 14.
- `GUI_Screen_Copy` -> `GFX_Screen_Copy` (`src/gfx.c:404`) unconditionally
  marks the **entire copied rectangle** dirty via `GFX_Screen_SetDirty`,
  regardless of how much of it actually changed content-wise.
- Result: every one of the ~10 scroll ticks marks a **304 x 14px** area dirty
  (304px spans 19 of the 20 possible 16px-wide c2p blocks — i.e. almost the
  full scanline width), forcing `c2p1x1_4_st` to reprocess ~4256 pixels/tick
  for 10 consecutive ticks, even though visually only a 1px-tall sliver of
  new content is being revealed each tick (the rest of the block is just
  being shifted, or is unchanged repeated content).

## Why it's disproportionate
A scrolling blit re-marks its whole destination rectangle dirty on every
step, even though most rows within it did not change content between one
tick and the next (only shifted by 1 row). The c2p/dirty-rect system has no
concept of "moved but unchanged" vs "actually modified" - it always
re-converts the whole rect.

## Earlier ideas
- Only mark dirty the newly-exposed 1px row per tick, if the rest of the
  scrolled content can be shown to already be present/correct on-screen
  (may not hold true since SCREEN_0 is the display target and content is
  genuinely shifting there).
- Reduce scroll step granularity/frequency (e.g. fewer, larger steps) to
  amortize the fixed per-call overhead - trades smoothness for speed.
- Investigate whether the banner width (304px / 19 blocks) can be narrowed -
  actual text is unlikely to use the full widget width every time, but the
  copy currently always uses the full `g_curWidgetWidth`.
- General: consider whether GFX_Screen_Copy could accept/produce a tighter
  dirty rect when the source/dest content is known to be identical in some
  sub-region (probably not worth the complexity vs. just reducing the copy
  area/frequency).

## Status
Implemented as a planar sliding-window cache. No persistent chunky
staging buffer or cache of individual animation phases is needed.
