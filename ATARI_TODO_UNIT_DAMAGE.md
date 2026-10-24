# ST/STE unit damage reduction checklist

Scope: native-planar ST/STE only. TT/Falcon and other video backends retain
their original invalidation. Preserve simulation, animation cadence, occupancy,
fog, minimap updates and house/visibility accounting.

The committed STE12/12a baseline is recorded below. The current experimental
native harvester registration footprint is described in its own section;
it intentionally changes callback coverage, not the component-bound repair.

## Batch progression

The first batch stopped after **five of the ten audit rows** and was profiled
in STE11. The second batch completes the remaining five rows, current-harvest
and genuine-rotation bounds, explosion bounds and unchanged-spice suppression.
A checked row records implemented scope, not measured savings or a claim that
all possible optimization is exhausted.

| Batch | Cause | Original work | Change / remaining work |
|---|---|---|---|
| [x] | Harvest bookkeeping | Broad redraw after changing `amount` / `inTransport` | State-only update: preserve accounting and key clearing; no native redraw or tile damage. Real spice changes still invalidate terrain separately. |
| [x] | Harvest animation | Current position plus two historical positions, potentially three 5x5 regions | Old attachment-frame bounds, real directional offset and wobble, before phase change. No visual history traversal; registration/removal history remains. |
| [x] | Body/turret rotation | Generic damage on either 8- or 16-direction bucket changes | Skip unchanged native ground 8-direction buckets. Real turns mark old changed body/attachment/turret bounds, including offset turrets. Instant turns prepare old geometry too. |
| [x] | Blink/deviation recolour | Background repair despite unchanged opacity; expiry forces 5x5 | Repaint-only for recolour. Leaving HARVEST explicitly marks its old attachment before action changes; deviation retains conservative current-component repair where applicable. |
| [x] | Stop / far-target approach | Generic redraw for speed or target-orientation changes | State-only update. Keep near-target position-adjustment damage and later actual rotation/movement notifications. |
| [x] | Walking animation | Generic dimension-based damage, plus candidate halo | Mark actual old body bounds before frame change, including between-tile positions; queue the new body independently. |
| [x] | Selection changes | Generic unit damage, including smoke/harvester expansion | Repair old marker only before changing selection; repaint old/new composites and clear keys. Structure/placement selection coverage remains separate. |
| [x] | Successful firing | Final generic redraw after cooldown/salvo bookkeeping | Final notification is state-only. Sandworm victim/removal/addition work remains intact. |
| [x] | Death/idle frames, infantry formation, carryall load | Generic updates for genuine graphic changes | Prepare old components before explicit frame/type/load changes. Skip identical explicit frame/idle-offset requests; preserve RNG order. |
| [x] | Movement, placement, removal, hiding, deployment | Occupancy/fog/minimap work and old-image repair | Old actual geometry before position/wobble/cleanup changes; original registration footprints and history retained. Native pickup omits the redundant removal preceding `Unit_Hide`. |

## Implementation contract

- `Unit_UpdateMap` retains remove/add/redraw modes and adds repaint/state and
  prepared-removal modes. Repaint/state become the old redraw mode outside native
  planar video; prepared removal becomes ordinary removal.
- State-only does not clear existing dirty flags or counters: previously queued
  real movement/frame damage must survive.
- Repaint-only keeps the owning unit independently dirty, so the renderer does
  not require a dirty anchor tile to submit it. Opacity masks are independent of
  palette/remap variants in the planar component cache.
- Before-mutation hooks mark old body/layer bounds through the same selectors
  used by drawing. Repaint queues new graphics; it does not itself repair
  terrain. Generic native redraw/removal also uses actual component geometry.
- Removal callbacks retain occupancy/minimap work and viewport candidates,
  without turning every registration tile into terrain repair. The radius-based
  5x5 registration branch is intentionally unchanged.
- Wobble is chosen at the original RNG point but assigned after departure
  repair. Smoke start/clear and spice depletion also prepare disappearing or
  changing layers before mutating their render inputs.
- Existing smoke-local damage and its accepted neighbour-overlap limitations
  are unchanged. Repaint-only updates also add no neighbour candidates; the
  full composite still publishes damage through the existing filter. As with
  smoke-local damage, a clean neighbour anchored outside the candidate cells
  may retain incorrect cross-tile overlap order.
- Other component repairs still use `Map_Update(0)` and its existing shared
  candidate halo. No new filtering passes, damage-source records or persistent
  previous-draw bounds.

## Profile context, not promised savings

STE10 saw 267 harvest-bookkeeping notifications costing 0.91 ms per viewport
pass inside `Unit_UpdateMap`. Active harvest animation cost 1.24 ms/pass.
The two harvester-history traversals together cost 3.58 ms/pass **across all
update types**; only presentation work is reduced. These timings overlap and
must not be added. Rotation generated 1,527 invalidations, but the capture does
not say how many changed only a 16-direction bucket.

### STE11 results

The capture matches the preserved five-row build: 38,725 program instruction
samples validated against its executable, with byte-identical GUI/viewport
objects to STE10. The batch boundary remains unchanged.

| Metric | STE10 | STE11 | Change |
|---|---:|---:|---:|
| Viewport passes/second | 8.39 | 11.68 | +39.1% |
| Viewport inclusive ms/call | 36.61 | 23.75 | -35.1% |
| Terrain inclusive ms/pass | 9.37 | 5.56 | -40.7% |
| Map_Update variants + Map_UpdateAround own ms/pass | 11.62 | 6.95 | -40.2% |
| Sprite publications/pass | 7.35 | 4.37 | -40.6% |

Per-notification costs show that the changed paths actually benefited, not
just that the captures have different lengths or frame rates:

| Unit_UpdateMap caller/reason | STE10 ms/call | STE11 ms/call |
|---|---:|---:|
| Harvest bookkeeping | 13.45 | 0.218 |
| Active harvest animation | 12.49 | 5.12 |
| Blink | 3.88 | 0.189 |
| Stop | 4.69 | 0.196 |

STE11 recorded 792 returns through the new unchanged-8-direction ground
rotation guard. The harvester visual-history guard ran 456 times, skipping
both history traversals each time (912 omitted Map_UpdateAround calls).
Registration/history work remains: its two call sites together took
2.33 ms/pass versus 3.58 in STE10, across different workloads; this remaining
cost is not all redundant presentation damage.

These are not identical-scene runs, so +39.1% throughput is not an isolated
speedup measurement. Native script dispatches/second were nearly unchanged
(2,756 -> 2,702, -2.0%); their -29.5% count per viewport pass largely reflects
more frames per second, not proof of a comparably lighter simulation.
Far-target approach was not exercised. Deviation-colour changes were not
demonstrated by the profile. Cache lookups remain 99.11% hits.

### STE12 results

The capture matches the second-batch executable: 39,247 sampled program
instructions validated, over 292.91 seconds and 4,117 viewport passes.
GUI objects differ, but the reused cache/filter counter sites were checked
individually against both object disassemblies.

| Metric | STE11 | STE12 | Change |
|---|---:|---:|---:|
| Viewport passes/second | 11.68 | 14.06 | +20.4% |
| Viewport inclusive ms/call | 23.75 | 16.42 | -30.9% |
| Terrain inclusive ms/pass | 5.56 | 2.49 | -55.1% |
| Map traversal/update + bounds helpers ms/pass | 6.95 | 4.10 | -41.1% |
| Sprite publications/pass | 4.37 | 2.48 | -43.2% |
| Plain tile publications/pass | 13.14 | 5.81 | -55.8% |

Map_Update variants + Map_UpdateAround alone fall from 6.95 to 2.77 ms/pass.
The new bounds work costs another 1.33 ms/pass, included in the 4.10 above:
own Map_UpdateSprite/DamageUnit/Prepare work plus damage-side shared-selector
calls, without double-counting nested map updates or charging drawing-side
selectors as new repair overhead.

Traced helper time per animation notification, including old-bounds preparation
and repaint in STE12, falls from 5.12 to approximately 0.96 ms for active
harvesting and 1.77 to 0.72 ms for walking. These are helper costs, not the
entire animation-loop cost. Partial trace boundaries leave 342 harvest-prepare
versus 343 repaint records; the walking pair has 78 records each.

Both Map_UpdateAround -> Map_Update(0) call sites execute zero times in STE12.
Wide registration/candidate callbacks remain active; this is not evidence that
the general 5x5 branch was removed. Spice fixup performs 25 final-graphic
comparisons, suppresses 14 unchanged repairs and retains 11 actual changes.
That path is too rare here to explain the overall gain. Composite lookups
remain 99.14% hits.

The captures are not controlled identical-scene benchmarks. Script dispatches
per second rise slightly, 2,702 -> 2,787 (+3.2%), while their count per viewport
pass falls with the increased rendering throughput. Neither those counts nor
the profile establish visual correctness or resolved halo/overlap behavior.

Subsequent user context: the harvester was outside the viewport for a
significant part of STE12. This can materially affect terrain repairs, sprite
redraws and throughput, so the cross-capture percentages must not be attributed
entirely to the code changes. Even per-notification costs depend on visibility.
Harvester draw submissions are 919 in STE11 versus 556 in STE12
(2.41 versus 1.90 per second), but those counters combine scene visibility and
changed redraw eligibility; they cannot measure time on screen or isolate its
contribution. A harvester-visible comparison would strengthen attribution.
The user reports substantially less noticeable flicker, but not its elimination.

### STE12a additional workload

Validated 40,248 program samples against the same executable. Over 388.03
seconds and 4,907 viewport passes, STE12a records 1,351 harvester submissions
(3.48/s, versus STE11's 2.41/s and STE12's 1.90/s). These are redraw submissions,
not visible-time counters. The harvester was still absent for part of the run;
the user reports that faster gameplay changed siege and harvester routes, so
an exact old playthrough is neither feasible nor required.

STE12a reaches 12.65 viewport passes/s (+8.3% versus STE11), 18.88 ms per
viewport call (-20.5%), 2.96 ms terrain/pass (-46.8%) and 2.77 sprite
publications/pass (-36.5%). Script dispatches/s are 2,947 versus STE11's
2,702 (+9.1%). The harvest bounds+repaint helpers total about 1.24 ms per
notification, versus 5.12 in STE11. This supports benefits in another, more
harvester-active workload, without claiming an isolated same-scene speedup.

### Shared halo audit

Three separate mechanisms can recruit/redraw nearby units:

1. `Map_UpdateSprite` currently uses `Map_Update(0)`: actual old-component
   repair tiles also mark a 3x3 candidate halo (`src/map.c:608-647`).
2. Registration still marks candidates across its original footprint, including
   5x5/history visits. That policy remains a separate follow-up.
3. In the STE12/12a baseline, every accepted composite adds its entire
   tile-rounded bounding rectangle to the cumulative sprite-damage filter.
   A later clean candidate can therefore pass without actually touching an
   earlier sprite. The rectangle includes transparent gaps between attachments.

A production-function harness in session artifacts (`halo-audit.py`) confirms
that A=[0,17), B=[31,33), C=[47,49), at the same vertical interval, can form
an accepted A->B->C chain despite 14-pixel gaps. Candidate admission remains a
separate prerequisite; a halo/registration visit supplies it. This establishes
a mechanism for non-touching neighbour redraw, not a capture-level count of
which source caused each publication.

An initially proposed experiment was single-tile mode 4 for sprite-originated
component repairs, keeping generic terrain/fog/structure `Map_Update(0)`,
registration and the cumulative filter unchanged. It would remove the
extra candidate halo, not tile-rounded erasure or all neighbour redraw.
Omitting overhanging clean neighbours can leave erased pixels/order artifacts,
as already accepted for smoke-local updates; extending that policy is a
behavioral decision, not a universally correctness-preserving optimization.
That proposal was not implemented; the user instead chose the clean-relay
experiment below. The candidate halo remains unchanged.

Prior STE8/STE9 decisions remain relevant: ordinary body-to-body ordering flips
were deliberately accepted; infantry underneath crushing vehicles and smoke
coverage were the important exceptions. STE8 implemented infantry-only
propagation and separate smoke publication. STE9 restored baked smoke and
tested an infantry/downward guard with source records. These implementations
were reverted for performance/bookkeeping cost, not because those accepted
ordering tradeoffs were disproved. The current unrestricted cumulative filter
is the restored baseline, not evidence that general painter-order preservation
is required. Smoke is currently baked into composites, so an always-on-top
smoke rule is not guaranteed by the present implementation.

STE9 directly suppressed only 54 candidates while added measured bookkeeping
blocks cost about 0.344 ms/pass; nearly 98% of accepted ground draws already
qualified through independent dirtiness/base damage. Those counts predate
the upstream damage reductions and cannot establish today's propagation cost
or justify retaining all cascades. Terrain-erasure dependencies must remain
distinct from ordering-only sprite publication dependencies.

The STE12/12a baseline filter branch counters distinguish clean accepted candidates:
STE12 has 5,104 clean acceptances out of 10,227 total; STE12a has 6,333 out
of 13,622 (46.5%, or 1.29 per viewport pass). In STE12a the remaining
acceptances are 6,999 independently dirty and 290 with the filter disabled.
These totals reconcile with the GUI acceptance counter. They do not distinguish
original terrain/dirty-source hits from relay-only hits, nor say whether each
clean publication expands the bitmap. Preventing clean sprites from relaying
would keep their own necessary draws and remove only later relay-dependent
publications. Terrain repair and harvester self-flicker are not directly
reduced by that rule. Any ordering tradeoff must still consider infantry and
smoke rather than assuming all clean publications are harmless.

### Withdrawn clean-ground relay experiment (STE13)

**Reverted after STE13.** The current renderer is restored to the STE12/12a
implementation: every accepted sprite propagates its full rounded composite
rectangle. The narrow strip, infantry-anchor exception and extra draw-call
arguments described below were removed together, including their experimental
tests. The proven unit/effect/spice damage improvements remain. This section
records the withdrawn experiment, not the current rendering contract.

- [x] Retain the original clean-sprite acceptance test against any intersecting
  accumulated-damage tile.
- [x] Accepted clean ground sprites add only the row below their logical anchor,
  horizontally intersected with rounded composite bounds and anchor column +/-1.
  The strip is clipped to the viewport and contains at most three columns.
- [x] Clean infantry gets that same strip and additionally ORs its anchor tile.
  The anchor write is redundant when already damaged, but can extend damage
  when a between-tile body qualified through its non-anchor portion.
- [x] Dirty sprites, non-ground sprites, selection-outline propagation and
  forced/scroll/non-native handling retain their previous behavior.
- [x] Pass the current logical anchor and infantry status by value through
  the existing draw call. No extra bitmap, source records, unit-history fields,
  neighbour lookup, tracked-target restriction or separate smoke pass.
- [x] Keep pending terrain repair before even a clean sprite publication.
  The filter creates no terrain repair, registration or candidate bits.
- [x] 21 focused renderer/cache/repair-order/selection tests, with sanitizers
  where supported; final added chain/rejection cases rechecked separately.
- [x] Assertion-enabled trusted 68000 compilation of both changed C files
  and `/usr/bin:/bin` release build.
- [ ] User visual assessment, especially harvester neighbours, infantry/crushing
  and smoke overlap.
- [x] STE13 matching-build profile: no observed publication reduction; increased
  clean redraw rate and a verified new-chain mechanism, detailed below.

Ordinary same-row body ordering is deliberately relaxed. Smoke remains baked
into composites; this strip is the agreed heuristic, not an always-on-top
guarantee and not a smoke-height/source test. Permitted downward chains remain,
and already-published earlier units cannot be revisited by this filter.
The ground anchor comes from the current logical packed tile, not a composite
edge, cached top-left or wobble-shifted display position.

Regression coverage exercises retained damage after terrain consumption,
dirty-A -> clean-B -> skipped-C chains across 14-pixel gaps, strip-only
successors, infantry anchor/no-op cases, clean rejection, viewport clipping,
offscreen anchors and exhaustive 1..5-column bounds against the three-column
cap. Draw-dispatch tests cover native and legacy modes, palette/remap argument
ordering, harvester temporary keys and unchanged composite identity.

The withdrawn STE13 executable had SHA-256
`5ae88ff24bd08586286b9b5cbc425a54a7884486494c01b836b7f7a53b61485e`.
Its matching executable/objects remain archived as `clean-ground-relay-*` in
session artifacts. The STE12/12a baseline archives are preserved unchanged.

### STE13 results: the downward strip is not purely restrictive

The capture matches the clean-ground-relay executable above: 41,304 sampled
program instructions validated, over 303.80 seconds and 3,312 viewport passes.
The current renderer objects match the archived build; `unit.o` and `map.o`
are byte-identical to their STE12/12a counterparts.

| Metric | STE12a | STE13 | Change |
|---|---:|---:|---:|
| Viewport passes/second | 12.65 | 10.90 | -13.8% |
| Viewport inclusive ms/call | 18.88 | 23.68 | +25.4% |
| Sprite publications/pass | 2.77 | 4.54 | +63.7% |
| Sprite publications/second | 35.08 | 49.50 | +41.1% |
| Clean filter acceptances/second | 16.32 | 30.65 | +87.8% |
| Independently dirty acceptances/second | 18.04 | 18.28 | +1.4% |
| Terrain inclusive ms/pass | 2.96 | 3.24 | +9.6% |
| Filter own ms/pass | 0.515 | 0.950 | +84.6% |
| Filter own microseconds/request | 97.8 | 132.7 | +35.7% |

Per-second counts matter here because a slower viewport accumulates more work
per pass. Almost all of the publication-rate growth is in clean acceptances,
not independently dirty sprites. Terrain cost per wall-clock second actually
falls from 37.42 to 35.36 ms; plain tile publications fall from 85.22 to 79.50/s.
Harvester submissions are nearly unchanged at 3.48 versus 3.51/s, although
these are not visible-time measurements. Script dispatches rise 7.2%, from
2,947 to 3,159/s. Spatial density, ordering and scene differences remain
confounders: these captures cannot isolate the rule's exact causal cost.

STE13 records 23,740 native requests, 23,714 filter calls and 15,042 accepted
requests: 5,554 independently dirty, 9,311 clean and 177 filter-disabled.
Of the clean acceptances, 8,372 are ground sprites using the new rule and
939 retain non-ground propagation. The strip OR executes 7,516 times and
the additional infantry-anchor OR 214 times. These count executed ORs, not
newly set bits or publications attributable to a particular source.
Actual masked sprite publications total 15,038. Composite lookup hits remain
99.15% (201 misses, 175 completed fills).

The clean-rule blocks themselves cost 0.161 ms/pass and their GUI vararg
parsing blocks 0.082 ms/pass. These are measured block costs, not isolated
net overhead: they exclude other dispatch/compiler changes and replace some
old full-rectangle work. GCC now inlines the native compositor into
`GUI_DrawSprite`, so old GUI counter offsets are invalid. The verified new
`gui.o` sites are request `0x4ac8`, filter call `0x4cb6`, accepted `0x4cc6`
and miss `0x4db4`; harvester NULL-key sites in `viewport.o` are `0x4190`
and `0x4ac6`. Reproduction and counters are in session
`battleste13-details.py/.json/.log`.

There is a concrete mechanism for extra clean draws: the strip is horizontally
bounded but not restricted to the composite's vertical bounds. A tile-centred
16x16 body can therefore mark the next row even though it wrote no pixels
there. A later clean unit in that row can repeat the operation, forming a
vertical or diagonal cascade that the old full-bounds filter would not create.

A sanitizer-enabled production-function harness in session
`clean-relay-row-audit.py/.log` demonstrates the difference: offer ten
tile-centred, vertically adjacent, non-overlapping bodies, all assumed already
admitted as candidates in top-to-bottom order, with terrain damage only under
the first. The previous full-rectangle rule accepts **one**; the new strip
accepts **all ten**. No terrain repairs or candidate recruitment are added.
This proves the new rule can increase propagation, not how often that happened
in STE13. The original horizontal-gap suppression remains valid too.

No renderer code or binary was changed during the profile analysis itself.
The subsequent decision was to discard this propagation experiment entirely,
not refine its strip. STE12/12a full-rectangle propagation and draw interfaces
were restored while retaining the earlier component-bound terrain improvements.
Any future propagation experiment requires a separate decision.

### Accepted STE12/12a restoration

The original cumulative sprite filter and draw interfaces are restored with
no STE13 relay code or experimental test changes remaining. Both proven
invalidation batches, smoke-local repairs, shared component selectors,
explosion bounds and unchanged-spice suppression are retained.

The restored trusted 68000 release is byte-for-byte identical to the archived
STE12/12a executable, SHA-256
`6ef16938bb23979f605853b488f4bc263962e2f66928802315d5a701c2b51e12`.
All 34 focused tests passed across sprite bounds, unit damage, smoke timing,
unit recount, sprite cache/damage, animation damage, phase reversal and planar
selection, with sanitizers where supported. This is the accepted implementation
baseline; the STE13 artifacts remain only for historical analysis.

## First-batch validation / progression

- [x] Focused native/legacy damage, registration and rotation regressions.
- [x] Script behavior and animation/state equivalence.
- [x] Trusted `/usr/bin:/bin` 68000 compilation and release build.
- [x] STE11 profile: matching build and observed invalidation/drawing reductions.
- [ ] User visual check for overlap, recolour and harvesting regressions.

The focused run passed 17 tests across `test_unit_damage`,
`test_unit_smoke_damage`, `test_unit_recount`, `test_viewport_sprite_damage`
and `test_viewport_sprite_cache`, with ASan/UBSan enabled for harnesses
supporting `TEST_CFLAGS`. It checks all update modes on native and legacy
backends, pending-damage preservation, 75-to-25 tile repair reduction for
three separate active-harvester regions, unchanged registration callbacks,
rotation state/bucket equivalence, script random/timing/spice effects and
the deviation/harvest-layer exception.

Reproduce with:

```sh
PATH=/usr/bin:/bin PYTHONPATH=.:tools \
TEST_CFLAGS='-fsanitize=address,undefined -fno-omit-frame-pointer -fno-pie -no-pie' \
python3 -m unittest tools.test_unit_damage tools.test_unit_smoke_damage \
  tools.test_unit_recount tools.test_viewport_sprite_damage \
  tools.test_viewport_sprite_cache
PATH=/usr/bin:/bin make -s -j2
```

## Second-batch validation / progression

- [x] Renderer-derived component geometry, odd dimensions, subtile positions,
  wobble, directional harvest offsets, death frames and air/load variants.
- [x] Old-frame repair before walking/harvest advancement, explicit death-frame
  shrink/repeated-frame suppression, incremental/instant rotation and zero-position
  initialization.
- [x] Real removal callback occupancy/destination/forced-cleanup behavior;
  native viewport-only versus legacy terrain repair.
- [x] Movement-prefix regression: old wobble through departure, unchanged RNG
  consumption/order including track-animation calls.
- [x] Explosion shrink/move/stop, repeated-frame suppression and legacy path.
- [x] Spice final-graphic suppression, centre grade changes, world edges and
  disappearing harvest-layer hook.
- [x] Final sanitizer-supported focused regression run: 23 tests; assertion-enabled
  compilation of all six changed C files and trusted 68000 release build.
- [x] STE12 matching-build profile and measured changed-path reductions.
- [x] User reports substantially reduced, but not eliminated, flicker.
- [ ] New-build visual check for halo/overlap and selection/message coverage.

The additional geometry/effect/spice regressions are in
`tools/test_sprite_bounds.py`. Reproduce the complete focused run with:

```sh
PATH=/usr/bin:/bin PYTHONPATH=.:tools \
TEST_CFLAGS='-fsanitize=address,undefined -fno-omit-frame-pointer -fno-pie -no-pie' \
python3 -m unittest tools.test_sprite_bounds tools.test_unit_damage \
  tools.test_unit_smoke_damage tools.test_unit_recount \
  tools.test_viewport_sprite_cache tools.test_viewport_sprite_damage \
  tools.test_animation_damage
PATH=/usr/bin:/bin make -s -j2
```

The release executable is `bin/opendune.tos`; its matching executable/objects
are preserved as `remaining-damage-bounds-*` in session artifacts, separately
from STE11. Existing strategic-map `snprintf` and unused factory-scroll warnings
remain unrelated to this batch.

## Remaining registration/candidate audit (STE12/12a)

**Audit only; no runtime change.** This examines the upstream registration and
candidate producer, not the withdrawn clean-composite propagation experiment.
The restored STE12/12a executable and its matching `map.o`/`unit.o` were used.
The existing capture analyses validate 39,247 / 40,248 program instruction
samples respectively. A reproducible `registration-callback-audit.py`, its JSON
results and matching disassemblies are preserved in session artifacts.
Source line references in this audit refer to baseline commit `9217793e`;
the subsequent movement-counter probe is described separately below.

Counts below come from executed instruction sites, including individual
unrolled 5x5 callback sites. Timings use available caller records; those records
omit a few calls and are not a complete per-call trace. All costs are
**whole-map work normalized per viewport pass**, not time spent exclusively
inside viewport drawing or on visible units. Inclusive parent/child costs
overlap and must not be added.

### Traversals and callback costs

| Measured work | STE12 | STE12a |
|---|---:|---:|
| `Map_UpdateAround` entries | 8,661 | 12,290 |
| Zero-position early returns | 143 | 143 |
| Smaller-footprint traversals | 6,278 | 8,805 |
| 5x5 traversals | 2,240 | 3,342 |
| Smaller-footprint tile visits | 47,584 | 68,978 |
| 5x5 tile visits | 56,000 | 83,550 |
| `Unit_AddToTile` calls | 50,545 | 75,243 |
| `Unit_RemoveFromTile` calls | 47,570 | 70,938 |
| Candidate-only callback-1 calls | 5,469 | 6,347 |
| `Map_UpdateAround` own ms/pass | 1.390 | 1.701 |
| `Map_UpdateAround` available inclusive ms/pass | 5.258 | 6.585 |
| Both harvester-history calls, available inclusive ms/pass | 1.836 | 2.631 |

No radius-zero return or direct callback-0 terrain call executed in either
capture. Every measured 5x5 traversal visited all 25 cells; this does not remove
the need for boundary clipping in general. In STE12a, 5x5 accounts for 27.2%
of entries but 54.8% of tile visits. Smaller footprints still account for a
substantial part of the work:

| STE12a traversal branch | ADD | REMOVE | Candidate-only | Own ms/pass |
|---|---:|---:|---:|---:|
| Smaller footprint | 32,518 | 30,113 | 6,347 | 0.967 |
| 5x5 | 42,725 | 40,825 | 0 | 0.646 |
| Shared entry/return | - | - | - | 0.088 |

The ADD/REMOVE callbacks cost 2.543 / 2.048 inclusive ms/pass respectively;
their own work is 0.582 / 0.765 ms/pass. Candidate bitmap address/mask
calculation, OR and counter increment inside `Map_UpdateAround` account for
0.452 ms/pass, already included in its own 1.701 ms/pass. This is measured
presentation bookkeeping, not evidence that all of it can safely disappear.

### Current versus historical positions

The matching `Unit_UpdateMap.part.0` call sites separate the STE12a work:

| Call site | Calls | Available inclusive ms/pass |
|---|---:|---:|
| Current ground position, dimension + 3 | 5,503 | 2.670 |
| Current ground position, forced radius 33 | 1,193 | 1.083 |
| Harvester `targetPreLast` | 1,982 | 1.297 |
| Harvester `targetLast` | 1,982 | 1.334 |
| Native air ADD | 1,630 | 0.200 |

The two history calls are about 40% of available `Map_UpdateAround` inclusive
time. They remain registration/removal traversals, not leftover harvest-frame
damage notifications. The harvester uses the same selected radius for its
current and both historical positions (`src/unit.c:2683-2695`); history is
updated on completed ground movement and cleared on structure entry
(`src/unit.c:1558-1563,1600-1603`). The aggregate capture cannot cross-tabulate
history/current calls with each radius, coordinate overlap, or callback outcome.
Do not infer that all historical visits, or all 5x5 visits, are redundant.

### What the callbacks actually do

`Unit_AddToTile` does not register the unit on every visited tile. Anchor
occupancy is assigned in `Unit_UpdateMap` before the traversal
(`src/unit.c:2668-2671`): 1,688 such assignments occur in STE12a. The callback
instead requests unveiling, minimap dirtiness and candidate eligibility
(`src/unit.c:2724-2729`).

Of 70,938 REMOVE callbacks, 16,132 encounter an occupied tile and 7,949 find
this particular unit. They clear occupancy 1,698 times (2.39% of all calls);
6,251 matching destination tiles are deliberately preserved. No forced
same-destination clear executed here. These are real conditional simulation
effects, even though most checks do not clear anything
(`src/unit.c:2704-2721`). Removing the broad scan without proving the destination,
forced-removal and historical cleanup invariants is not justified.

Fog/minimap outcomes also show why cheap returns must not be confused with
permission to skip the callback:

- Global `Map_UnveilTile`: 89,033 calls, including the 75,243 ADD requests.
  Only 29,267 pass the player-house test; 1,641 enter the unveil/overlay-recompute
  path. This is not a count of first discoveries: already-unveiled but partially
  fogged tiles also enter it. Its five neighbour checks execute 8,205 times,
  assign overlays 5,527 times and queue 2,317 new pending visible terrain repairs.
  Their `Map_Update(0)` is compiler-inlined, so those repairs do not appear as
  calls to the standalone `Map_Update` function. These global outcomes cannot
  be attributed specifically to ADD rather than other unveil callers.
- Standalone `Map_MarkTileDirty`: 147,456 calls, of which 146,181 originate in
  registration callbacks. There are 134,427 already-marked returns and 13,029
  newly set/enqueued bits. At least 11,754 of those new bits must come from
  registration, since only 1,275 calls have another origin. An additional 960
  new bits/enqueues occur in the compiler-inlined copy inside unveiling.
  New queue entries demonstrate changed bookkeeping, not necessarily a changed
  final minimap image. No queue-capacity rejection executed in these captures;
  dirty-bit retention and the existing full-queue scan must still survive.

The fog behaviour is at `src/map.c:1367-1445`; the minimap deduplication is at
`src/map.c:1757-1764`, with its queue consumer/refill at
`src/gui/viewport.c:1353-1427`.

### Proven redundancy versus a new candidate policy

There is a narrower correctness-preserving opportunity before changing any
footprint:

1. Both `Map_UpdateAround` loops set `g_dirtyViewport[curPacked]` and increment
   its preparation trigger **before** dispatching the callback.
2. ADD and native REMOVE finish with `Map_Update(curPacked, 1, false)`.
   Callback 1 calls `Map_Update(curPacked, 3, false)` directly.
3. Modes 1/2/3 only OR that same candidate bit, or return when outside the
   visibility gate. They do not queue terrain, increment the trigger, or update
   selection state (`src/map.c:639-693`). Callback fog work never clears it.
   The only production callers of ADD/REMOVE are these two loops.

Consequently the final candidate calls duplicate an existing bit. In STE12a
there are **146,181** such registration calls plus **6,347** candidate-only
calls. Their available callee costs are:

| Duplicate path | STE12 ms/pass | STE12a ms/pass |
|---|---:|---:|
| ADD -> `Map_Update(1)` | 0.613 | 0.851 |
| Native REMOVE -> `Map_Update(1)` | 0.575 | 0.805 |
| Callback 1 -> `Map_Update(3)` | 0.080 | 0.079 |
| Total available callee time | 1.268 | 1.736 |

For STE12a this is 21.95 ms of CPU per wall-clock second, about 2.2% of an
8 MHz CPU budget, before considering caller setup or replacement-code costs.
It is a measured optimization target, not a measured new-build speedup.
Eliminating these redundant calls in the guaranteed premarked context could
preserve **all existing candidates, occupancy, fog, minimap work and the
publication filter**, with no new tracking. Legacy REMOVE's `Map_Update(0)`
must remain.

This must not be inverted into dropping the outer candidate writes and
relying on the callbacks. Outer writes cover the whole map, whereas
`Map_Update` is gated by the 15x10 region based on `g_minimapPosition`, which
need not equal `g_viewportPosition` during scrolling. The nonzero
`g_dirtyViewportCount` also triggers row preparation. Native row preparation
can promote fully fogged candidate tiles into fog-cover repairs
(`src/gui/viewport.c:104-135,1010-1013`).

Broad redraw eligibility can be separated mechanically from occupancy/fog/
minimap callbacks, but **narrowing it remains a separate behavioural decision**.
Clean units still need their anchor admitted before the composite filter tests
their overhangs; no amount of later intersection testing rescues an omitted
candidate (`src/gui/viewport.c:1202`). Aggregate profiles do not record previous
candidate-bit values, unique visited tiles, or which registration visit recruited
which clean publication. Thus they cannot quantify how many sprite publications
a narrower registration footprint would safely avoid. This audit authorizes
neither a footprint shrink nor another propagation change.

## Withdrawn same-tile movement diagnostic

The temporary `Unit_CountMoveRegistration` probe was removed before the radius
experiment, together with its movement hook, counters, logging include and
probe-only test. No periodic movement-counter warnings remain.

The user's shortened sample ended at 919 same-tile and 83 crossed-tile pairs:
1,002 completed ground-movement REMOVE/ADD pairs, 91.7% staying within a tile,
and zero exact-position-unchanged pairs. These were cumulative counters, not
values to sum across log lines. They establish frequent within-tile movement,
not identical sampled footprints or permission to omit callback effects.

## STE14 experiment: normal harvester registration radius

In the STE14 build, native ST/STE ordinary harvester ADD/REMOVE keeps its normal
`dimension + 3` radius: **27**, even with `ACTION_HARVEST`, smoking, or both.
This selects the existing sampled smaller-footprint path, at most nine visits
per position, rather than the 25-cell 5x5 path. It is not a newly introduced
fixed 3x3 scan: exact cells still depend on subtile position and map boundaries.

The radius is selected once and reused at the current position,
`targetPreLast` and `targetLast`. All three traversals remain. At the three
separate tile-centred test positions, harvesting/smoking registration drops
from 75 to 27 callbacks per notification. Actual captures can differ because
positions overlap, footprints contain fewer cells, or history is zero/off-map.

Forced cleanup (`bulletIsBig`, as set by removal/hiding) retains radius 33 at
all three positions, including its destination-occupancy cleanup semantics.
Other unit types, TT/Falcon and non-TOS backends retain their original radius
selection. Component-bound old-image repair, the REMOVE/move/ADD sequence,
precise movement, dirty-state/accounting updates, callback bodies and cumulative
sprite propagation remain unchanged. No new tracking or scan-skipping rule
was added; the proven duplicate candidate-only calls are not removed here.

The experiment intentionally reduces the cells receiving candidate, unveiling
and minimap callbacks. It is not claimed to preserve every old fog edge or
cross-tile sprite ordering outcome. The configured harvester sight radius is
still 2, unchanged and equal to the light vehicles' setting. Destruction's
load-dependent `Map_FillCircleWithSpice` runs separately and is unchanged.

`tools/test_unit_damage.py` covers ADD/REMOVE at all three positions, harvesting
and smoking independently, combined flags, normal and forced radii, candidate
counts, zero/edge history, and unchanged other-backend/other-unit behavior.
The exhaustive update-mode cases now vary harvesting independently from the
forced-cleanup flag. The matching STE14 profile and the user's visual
assessment are recorded below.

### STE14 matching-capture assessment

`battleste14.txt` matches the experimental binary
`910e98fc044a440fcc8f3fcd75d1feef98cea5324944cfcb4bdd983f2e362819`:
40,301 sampled program instructions were validated against its executable.
The map, GUI and viewport objects are byte-identical to the archived STE12
objects. The complete ADD/REMOVE callback bodies are also byte-identical,
shifted by -0x3c in the new unit object; the changed current/history call sites
and anchor occupancy store were rechecked separately.

The experiment is active: the native harvester harvesting/smoking decision
ran 1,032 times, with no legacy-radius fallback. Both historical traversals
still ran 1,446 times each. Only 29 5x5 traversals remain, all on the expanded
current-position call path retained for the unchanged exceptional policies.

| Registration metric | STE12 | STE12a | STE14 |
| --- | ---: | ---: | ---: |
| Capture seconds | 292.91 | 388.03 | 355.305 |
| Viewport passes | 4,117 | 4,907 | 3,921 |
| `Map_UpdateAround` entries | 8,661 | 12,290 | 10,556 |
| Smaller / 5x5 traversals | 6,278 / 2,240 | 8,805 / 3,342 | 10,383 / 29 |
| Total visited cells, including repeats | 103,584 | 152,528 | 83,277 |
| ADD / REMOVE callbacks | 50,545 / 47,570 | 75,243 / 70,938 | 38,568 / 36,243 |
| ADD+REMOVE callbacks/second | 334.97 | 376.73 | 210.55 |
| `Map_UpdateAround` own ms/pass | 1.3905 | 1.7011 | 1.5475 |
| Available inclusive ms/pass | 5.2583 | 6.5845 | 5.0675 |
| Mean inclusive ms/history traversal | 3.1991 | 3.2587 | 1.8773 |

There are 144 zero-position returns in STE14, versus 143 in each baseline.
STE14's smaller path visits 82,552 cells and its 5x5 path visits only 725.
Compared with STE12a, ADD/REMOVE callbacks/second fall **44.1%**, available
inclusive traversal cost/pass falls **23.0%**, and the observed mean cost per
timed historical traversal falls **42.4%**. The mean pools the two history
call sites; their combined cost/pass is 1.3842 ms versus 2.6311 ms. That cost
is already inside the inclusive traversal total, not an extra saving to add.
These are whole-map registration costs normalized by viewport passes, not
costs restricted to visible tiles.

The publication and throughput measurements do **not** show an overall gain:

| Presentation/workload metric | STE12 | STE12a | STE14 |
| --- | ---: | ---: | ---: |
| Viewport passes/second | 14.06 | 12.65 | 11.04 |
| Inclusive viewport ms/timed call | 16.42 | 18.88 | 21.05 |
| Sprite publications/pass | 2.482 | 2.774 | 3.433 |
| Sprite publications/second | 34.89 | 35.08 | 37.89 |
| Clean sprite filter acceptances/second | 17.43 | 16.32 | 19.52 |
| Independently dirty acceptances/second | 16.65 | 18.04 | 18.02 |
| Terrain CPU ms/wall-second | 35.05 | 37.42 | 34.34 |
| Native script dispatches/second | 2,787 | 2,947 | 3,212 |

Against STE12a, clean acceptances/second rise 19.6%, independently dirty ones
are essentially unchanged, and sprite publications/second rise 8.0%.
The filter's own mean cost/request is nearly unchanged, 97.80 to 98.67 us;
its larger cost/pass is not evidence of a more expensive filter algorithm.
Narrower registration did not translate into fewer observed sprite
publications in this capture. Terrain cost/pass rises slightly, 2.9587 to
3.1114 ms, but terrain cost/wall-second falls 8.2%; there is no corresponding
terrain-publication surge to explain the lower pass rate.

The captures are different workloads, not a controlled replay: script
dispatches/second are 9.0% higher than STE12a, while harvester draw
submissions/second fall from 3.48 to 2.96 and history traversal frequency falls
20.3%. Draw submissions are not harvester visible-time measurements. Thus
the lower pass rate cannot be attributed to the radius change alone, and the
registration-cost reduction is not an isolated end-to-end speedup.

ADD still calls `Map_UnveilTile` once per callback: 38,568 of 52,822 global
calls. Fog-neighbour processing queues 2,122 new terrain repairs, approximately
5.97/second, essentially the same rate as STE12a's 2,317. Standalone minimap
marking sees 75,924 calls, 67,574 duplicate-bit returns and 8,350 new
bits/enqueues; unveiling's inlined path adds 972 new bits/enqueues. Queue
overflow remains zero. Aggregate totals cannot establish that the same fog
edges or candidate-dependent ordering were preserved.

The unchanged duplicate candidate-only calls now account for 1.1665 available
callee ms/pass, versus 1.7358 in STE12a; they have not been optimized away.
STE14's internal filter acceptance branches total 13,464 versus 13,463
caller-side acceptances and 13,461 masked-blit entries. The one-count internal
discrepancy is recorded explicitly rather than forcing reconciliation; the
caller/blit counts also reflect later clipping.

Reproduction artifacts are `battleste14-analysis.json/.log`,
`battleste14-details.py/.json/.log` and the matching unit/GUI disassemblies in
the session files directory. The comparison script checks unchanged object
and callback bytes, reconciles baseline counters, and records the new unit
sites and profile limitations. On 2026-10-24 the user reported that gameplay
looked visually correct, as far as they could assess. **The sampled gameplay
therefore has a positive visual assessment**, not exhaustive verification of
fog edges or sprite ordering. The profile independently confirms execution
and reduced registration work. No further runtime change or commit accompanies
this assessment.

## Current experiment: duplicate candidate calls and no ordinary targetPreLast

The next authorized build makes exactly two further reductions:

1. Remove the repeated candidate-only `Map_Update` calls after the outer
   traversal has already marked the tile.
2. Omit `targetPreLast` for ordinary native ST/STE harvesters, retaining
   `targetLast` and the current-position scan.

Both branches of `Map_UpdateAround` still set the candidate bit and increment
`g_dirtyViewportCount` before callback dispatch. Function 1 therefore needs
no further callback. `Unit_AddToTile` retains unveiling and minimap marking
but no longer repeats the candidate bit write. These shared-path removals
preserve behavior on every backend; they need no new per-tile native check.
Native `Unit_RemoveFromTile` retains occupancy cleanup and minimap marking
without its redundant candidate-only call. Legacy REMOVE still executes
`Map_Update(..., 0, false)` and retains its terrain repair and candidate halo.
Both registration callbacks are only called by `Map_UpdateAround`; their
source comments document the already-marked-candidate contract.

The native harvester history change is experimental and separate from that
behavior-preserving cleanup. Normal radius remains 27, including harvesting
and smoking. At distinct tile-centred positions it now visits 18 cells across
current position and `targetLast`, versus 27 across three regions in STE14.
The stored `targetPreLast` value is not cleared or otherwise changed.
Forced cleanup (`bulletIsBig`) retains both historical traversals and radius
33, visiting the same 75 cells in that test. Other units and other backends
retain their existing radius/history policy.

Component-bound image repair, dirty-state and visibility accounting,
destination occupancy protection, precise movement and REMOVE/move/ADD order
are unchanged. No movement-pair-specific scan suppression or sprite
propagation change is included. Omitting the older region intentionally
reduces its candidate/fog/minimap callback coverage; STE14's positive visual
assessment does not validate this new omission.

Regression coverage uses the production traversal and ADD/REMOVE callbacks
to check that no candidate-only calls remain, candidates are marked before
callback work, and counters, visibility gates, selection flags and legacy
terrain repairs are preserved. It covers small/5x5 footprints, zero/off-map
positions, map edges, ownership, destination protection and forced cleanup
in both TOS and non-TOS builds. Unit-update cases separately assert the exact
retained regions, callback counts and unchanged other-backend policies.

The current `bin/opendune.tos` SHA-256 is
`d0364c00bbddef869299c9cdfad9b9434b468946fb573f664f16b19424bdf69f`.
Its matching executable and complete release objects are preserved as
`registration-prelast-opendune.tos` and `registration-prelast-objects/` in the
session files directory, alongside the source patch and map/unit disassemblies.

The matching STE15 profile is assessed below; user visual assessment remains
pending for this combined build.
The STE14 gross timing scopes (1.1665 ms/pass in duplicate candidate callees
and 0.6771 ms/pass in `targetPreLast`) overlap and are not additive savings
estimates. **Stop here: do not omit `targetLast` before assessing this build.**

### STE15 matching-capture assessment

`battleste15.txt` matches the combined-build hash above: 41,487 sampled program
instructions were validated against the executable. The current map/unit
objects match `registration-prelast-objects/`; GUI and viewport objects remain
byte-identical to STE14. Changed map/unit instruction sites were rediscovered
from the archived disassemblies rather than reusing STE14 offsets.

Both intended changes are directly observed:

- No registration edge from `Map_UpdateAround`, `Unit_AddToTile` or
  `Unit_RemoveFromTile` calls standalone `Map_Update`. Native REMOVE's legacy
  terrain-call site and the traversal's terrain callback sites also execute
  zero times. Other legitimate callers still make 3,840 standalone
  `Map_Update` calls.
- The harvester history guard executes 1,010 times, all in native mode.
  `targetPreLast` runs only twice, through the forced-cleanup branch; 1,008
  ordinary older-position scans are omitted. `targetLast` still runs all
  1,010 times. Of the capture's 16 5x5 traversals, 400 cell visits are recorded;
  zero-position histories can still return without a traversal.

| Registration metric | STE14 | STE15 |
| --- | ---: | ---: |
| Capture seconds | 355.305 | 336.265 |
| Viewport passes | 3,921 | 3,754 |
| `Map_UpdateAround` entries | 10,556 | 7,902 |
| Total visited cells, including repeats | 83,277 | 60,772 |
| ADD / REMOVE callbacks | 38,568 / 36,243 | 27,065 / 25,410 |
| ADD+REMOVE callbacks/second | 210.55 | 156.05 |
| `Map_UpdateAround` own ms/pass | 1.5475 | 1.0781 |
| Available inclusive ms/pass | 5.0675 | 2.7780 |
| Available inclusive CPU ms/wall-second | 55.92 | 31.01 |
| Both history calls, inclusive ms/pass | 1.3842 | 0.3468 |
| Mean inclusive ms/retained `targetLast` traversal | 1.9185 | 1.2861 |

The observed inclusive registration budget drops **2.2895 ms/pass (45.2%)**;
own traversal cost/pass drops 30.3% and ADD/REMOVE callbacks/second drop 25.9%.
The combined history budget drops 74.9%, with only 0.00074 ms/pass left in the
forced `targetPreLast` calls and 0.34603 ms/pass in `targetLast`. The retained
history traversal itself is 33.0% cheaper per timed call, supporting the
candidate-call cleanup's benefit separately from omitting the older region.
These history times are already inside the inclusive registration total.
Relative to STE12a, observed registration cost/pass is now 2.7780 versus
6.5845 ms, a 57.8% reduction across the successive experiments.

These are whole-map CPU costs divided by viewport passes, not work inside the
viewport draw function. Nor are all observed differences isolated algorithmic
savings: harvester registration notification frequency also falls from
4.07/second to 3.00/second, while harvester draw submissions rise from 2.96
to 3.37/second. Submissions are not visible-time measurements.

| Presentation/workload metric | STE14 | STE15 |
| --- | ---: | ---: |
| Viewport passes/second | 11.04 | 11.16 |
| Inclusive viewport ms/timed call | 21.05 | 21.39 |
| Sprite publications/pass | 3.433 | 3.445 |
| Sprite publications/second | 37.89 | 38.45 |
| Clean sprite filter acceptances/second | 19.52 | 19.42 |
| Independently dirty acceptances/second | 18.02 | 18.44 |
| Terrain CPU ms/pass | 3.1114 | 3.2117 |
| Terrain CPU ms/wall-second | 34.34 | 35.85 |
| Native script dispatches/second | 3,212 | 3,293 |

Publication behavior is close to STE14: publications/pass rise only 0.34%,
clean acceptances/second fall 0.54%, and dirty acceptances/second rise 2.35%.
The filter's mean own cost/request remains essentially unchanged, 98.67 to
97.75 us. STE15's internal acceptances reconcile exactly:
6,530 clean + 6,202 independently dirty + 203 inactive = 12,935; there are
12,931 masked-blit entries after subsequent clipping.

Overall pass throughput is 1.2% higher, while viewport draw time/call is
1.6% higher. Terrain CPU/wall-second rises 4.4% and script dispatch rate
rises 2.5%. These different workloads therefore show a clear reduction in
targeted registration work, approximately stable publication behavior, but
not an isolated end-to-end frame-rate speedup.

Retained ADD callbacks make 27,065 unveil calls and 27,065 minimap tail jumps.
There are 40,716 global unveil calls and 1,431 unveil/recompute entries;
fog-neighbour processing queues 1,892 new terrain repairs. Standalone minimap
marking records 53,516 calls, 46,690 duplicate-bit returns and 6,826 new
bits/enqueues; unveiling's inlined path adds 955 new bits/enqueues. Queue
overflow remains zero. REMOVE clears 1,286 matching occupancy entries and
protects 4,358 matching destination entries; no forced destination clear is
observed. None of these aggregate counts proves preserved tile identities,
fog edges or sprite ordering.

Timing caveats: available timed traversal calls cover 7,899 of the 7,902
instruction-counted entries; three untimed caller records have non-C caller
attribution. Source call-site instruction counts nevertheless reconcile every
entry. ADD now tail-jumps to `Map_MarkTileDirty`, so those child edges lack
inclusive timing even though instruction counts prove the marking executes.
Do not interpret incomplete incoming minimap timings as removed work.

Reproduction artifacts are `battleste15-analysis.json/.log` and
`battleste15-details.py/.json/.log` in the session files directory. The latter
records current instruction sites, matching object hashes, reconciled
callbacks/counters, timing coverage and normalized STE12a/14/15 comparisons.
**Visual assessment of STE15 remains pending. `targetLast` is unchanged;
no further runtime reduction or commit accompanies this assessment.**

## Adjacent producers and deferred policy

- [x] Explosion frame damage: actual old sprite bounds, existing candidate halo.
- [x] Skip unchanged visual invalidation in `Map_FixupSpiceEdges`.
- [x] Explain and measure remaining 5x5/smaller registration callbacks and
  harvester-history costs; separate presentation bookkeeping from real effects.
- [x] Remove the proven duplicate candidate-only calls, preserving outer
  candidates/counters, callback side effects and legacy REMOVE terrain repair.
- [x] Implement the separately authorized native harvester normal-radius
  experiment at current and both historical positions; retain forced cleanup.
- [x] Assess the harvester-radius experiment with the matching STE14 capture.
- [x] User visual assessment of STE14: gameplay looked correct as far as the
  user could assess; general 5x5 registration/candidate policy remains separate.
- [x] Experimentally omit ordinary native harvester `targetPreLast` only;
  retain `targetLast` and both historical regions for forced cleanup.
- [x] Assess the combined duplicate-call/`targetPreLast` build with the
  matching STE15 profile.
- [ ] Assess STE15 visually before considering any `targetLast` reduction.
- [ ] Review the shared `Map_Update(0)` neighbour-candidate halo independently
  of actual terrain repairs from structures, animation, walls, fog and spice.
- [ ] Keep existing narrow shifted-scroll edge damage; full rebuild/message and
  structure-selection repairs need separate old/new coverage analysis.
- [ ] Optional cleanup: fold smoke-local damage into a named Unit_UpdateMap
  mode to share bookkeeping, preserving its accepted no-neighbour-halo policy.
  This was deferred after STE10; it is not a demonstrated major speed target.
