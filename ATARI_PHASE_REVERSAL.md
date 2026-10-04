# ST/STE viewport phase reversal: repair on first touch

## Agreed starting point

Start from `atari-st-sprite-cache`. Keep the engine's existing broad damage
estimates and sprite-redraw eligibility. Change when terrain is published,
not how simulation events register units or invalidate the viewport.

The goal is to shorten the visible interval between background restoration
and sprite replacement. This is not atomic presentation and does not promise
to eliminate flicker.

## Four steps

1. Run the existing terrain bookkeeping without drawing tiles. Preserve
   visible-damage detection, `g_dirtyViewport`, actor redraw decisions and
   selection-repaint decisions. `g_dirtyMinimap` remains the pending terrain
   repair set; despite its name, it selects viewport background reconstruction.
   A forced redraw must put all visible tiles into that set.
2. Draw the ground foreground in its existing painter order. Immediately
   before each draw, repair still-pending terrain tiles intersecting its
   complete clipped bounds, including turret, smoke and selection layers.
   Clear each repaired tile's `g_dirtyMinimap` bit, then draw the foreground.
   Apply the same rule to the building outline and explosions.
3. Repair the remaining pending terrain tiles. These include abandoned old
   sprite positions with no current foreground over them.
4. Draw aircraft last, using the existing redraw checks. An unchanged aircraft
   damaged by terrain reconstruction must be redrawn too. Clear viewport
   invalidation state only after the foreground passes are finished.

Restore each dirty tile at most once per viewport update. Repairing a shared
tile again before a later sprite would erase an earlier sprite. Conversely,
every tile intersecting a foreground draw must already be repaired before
that draw, so the final sweep cannot erase it.

No draw-command FIFO, grouping, per-unit footprint history, private tile
composition buffer or newly collected protection masks are needed for this
starting experiment. Existing cached sprite opacity masks are unchanged.
The pending tile bitset supplies the only per-tile state.

Uncached planar sprites finish private pixel rendering and opacity-mask
preparation before repairing terrain immediately ahead of publication.

Repair traversal reads each visible world-row range into a temporary local
bit mask. Empty rows are skipped, and the inner loop tests and shifts that
mask instead of looking up each tile's bit in memory. It stops when the
shifted mask is empty or the requested range ends; actual repairs still
clear the original bitset. Byte-wise extraction supports every viewport alignment
without unaligned word reads or a third-byte read past the map's end.

Scope is the eligible direct planar ST/STE viewport. Other machines,
off-screen drawing, fades and background-reading effects retain the existing
terrain-first fallback. This experiment does not change the baseline's
shadow/effect policy.

## Nominal versus actual damage: a later refinement

Initially, repair still follows the engine's nominal radii and neighbouring
tile estimates. That is deliberately independent of the publication-order
experiment.

This model offers a much simpler place to tighten excessive damage than the
FIFO/grouping and clipped-tile experiments: the pending repair set and the
repair-before-draw boundary. Actual clipped sprite/layer bounds are available
at the point of publication, without collecting and replaying commands.
Future bounds- or mask-derived damage can replace broad estimates there.

Current draw coverage alone is insufficient: movement, disappearance and
shrinking frames also leave damage at the previous rendered footprint.
Explicit terrain/fog/animation changes and newly exposed scroll edges must
remain repair sources. More precise damage must also retain inclusion of
otherwise unchanged foreground objects intersecting the affected area.
Those refinements may require additional footprint metadata; they are not
part of this initial implementation.

### Deferred follow-up: retain precise damage information

Revisit retaining precise damage information after the current experiment.
Keep broad engine invalidation for now. This follow-up concerns retained
damage provenance and footprints, rather than a pixel-comparison filter
in the final sweep.

The existing dirty bits coalesce causes, so the final sweep cannot distinguish
a nominal radius tile from actual old-sprite residue or an explicit background
change. The future design should distinguish explicit terrain/overlay/fog
changes and scroll exposure from sprite-derived repair, retaining previous
and current rendered footprints, including attachments and selection marks.
Disappearing sprites and shrinking frames must still repair their old pixels.

The harvester is a useful first target: harvesting selects a 5x5 neighbourhood
and also invalidates around `targetLast` and `targetPreLast`. Those overlapping
nominal regions can exceed its actual rendered damage. Preserve unit/tile
registration and inclusion of unchanged foreground objects affected by repair
while tightening presentation damage.

A late sweep filter alone cannot prevent unnecessary actor redraws already
selected earlier; precise damage should also feed those redraw decisions.
Treat this as separate from a possible harvester-local draw-first pivot,
which targets the repair-to-sprite exposure interval.

### Proposed sweep pruning by damage cause

Investigate the hypothesis that a remaining sweep tile can be retired without
painting when it has no explicit background-change reason, is fully unfogged,
and there are no aircraft or selection overlays on the scene. This is a
candidate for rejecting nominal-radius-only damage, not an established safe
rule or an implemented change.

The broad movement region is not solely a fog-discovery mechanism.
`Unit_UpdateMap()` chooses a radius from sprite dimension plus padding, with
larger regions for smoke, big bullets and harvesting (`src/unit.c:2513-2523`).
`Map_UpdateAround()` also performs unit/tile registration (`src/map.c:1067-1152`).
Separately, `Map_Update(..., 0, ...)` marks only the requested terrain tile
pending but marks a 3x3 foreground-redraw halo (`src/map.c:614-647`).
Fog discovery has its own path through `Map_UnveilTile()` and neighbouring
fog-overlay updates (`src/map.c:1330-1405`).

The four proposed checks are insufficient by themselves: an ordinary ground
unit can leave pixels in its previous tile even on fully revealed terrain
with no aircraft or selection. Its current draw repairs only tiles under
its current bounds, leaving the abandoned footprint for the final sweep.
Disappearing effects, shrinking frames and removed aircraft or selection
overlays likewise require retained old-footprint damage.

The supported refinement is to retire a tile only when its retained reasons
prove it is nominal-radius-only, with no unrepaired previous foreground
footprint and no explicit terrain, overlay, animation, fog-transition, scroll
exposure or forced-redraw requirement. A tile newly cleared of fog can already
look unfogged in map state while still requiring publication; current state
alone cannot prove that its displayed background is up to date. Reasons must
coexist when events overlap, rather than allowing one cause to overwrite
another. Preserve registration and foreground-redraw dependencies separately
from this terrain-repair decision.
